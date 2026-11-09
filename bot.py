"""Telegram delivery bot for Crypto Portfolio & PnL Tracker Pro.
Payments are verified manually by an administrator. This bot does not process payments.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

ROOT = Path(__file__).resolve().parent
ORDERS_FILE = Path(os.getenv("ORDERS_FILE", str(ROOT / "orders.json")))
PRODUCT_FILE = Path(os.getenv("PRODUCT_FILE", str(ROOT / "Crypto_Portfolio_and_PnL_Tracker_Pro.xlsx")))
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@your_admin_username").strip()
PRODUCT_NAME = "Crypto Portfolio & PnL Tracker Pro"
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("portfolio_bot")


def _load_orders() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(ORDERS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        log.exception("Could not read the orders database")
        raise RuntimeError("Orders database is unreadable; refusing to overwrite it")


def _save_orders(orders: dict[str, dict[str, Any]]) -> None:
    ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="orders-", suffix=".tmp", dir=ORDERS_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(orders, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_name, ORDERS_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    configured = context.application.bot_data["admin_id"]
    user = update.effective_user
    return bool(user and user.id == configured)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        f"سلام! به ربات تحویل {PRODUCT_NAME} خوش آمدید.\n"
        f"Welcome! This bot delivers {PRODUCT_NAME}.\n\n"
        "محصول: فایل اکسل برای ثبت و پیگیری پرتفوی رمزارز و سود/زیان (PnL).\n"
        "Product: an Excel workbook for tracking a crypto portfolio and profit/loss (PnL).\n\n"
        "برای ثبت سفارش /buy را بفرستید. تحویل فقط پس از بررسی و تأیید دستی پرداخت توسط مدیر انجام می‌شود؛ ربات پرداخت را بررسی یا پردازش نمی‌کند.\n"
        "Send /buy to create an order. Delivery happens only after the admin manually checks and confirms payment; the bot does not process or verify payments.\n\n"
        "این فایل ابزار ثبت اطلاعات است و توصیهٔ مالی یا تضمین نتیجه نیست.\n"
        "This is a record-keeping tool, not financial advice or a guarantee of results."
    )
    await update.effective_message.reply_text(text)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    order_id = "CP-" + uuid.uuid4().hex[:8].upper()
    orders = _load_orders()
    orders[order_id] = {
        "order_id": order_id,
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_orders(orders)
    admin_contact = ADMIN_CONTACT or "(admin contact not configured)"
    text = (
        f"سفارش شما برای {PRODUCT_NAME} ثبت شد.\nOrder created for {PRODUCT_NAME}.\n\n"
        f"شناسه سفارش / Order ID: {order_id}\n\n"
        f"برای هماهنگی پرداخت، خصوصی به مدیر پیام دهید: {admin_contact}\n"
        f"Contact the admin privately to arrange payment: {admin_contact}\n"
        "شناسه سفارش را برای مدیر بفرستید. تحویل فایل فقط پس از تأیید دستی مدیر انجام می‌شود.\n"
        "Send the order ID to the admin. The workbook is delivered only after the admin manually confirms payment."
    )
    await update.effective_message.reply_text(text)
    for admin_id in [context.application.bot_data["admin_id"]]:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(f"سفارش جدید / New order: {order_id}\n"
                      f"User ID: {user.id}\nUsername: @{user.username}" if user.username else
                      f"سفارش جدید / New order: {order_id}\nUser ID: {user.id}\nNo username set"),
            )
        except Exception:
            log.info("Could not notify admin about order %s", order_id, exc_info=True)


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update, context):
        await update.effective_message.reply_text("فقط مدیر مجاز است. / Admin only.")
        return
    orders = _load_orders()
    if not orders:
        await update.effective_message.reply_text("سفارشی ثبت نشده است. / No orders yet.")
        return
    lines = ["سفارش‌ها / Orders:"]
    for item in sorted(orders.values(), key=lambda x: x.get("created_at", "")):
        lines.append(
            f"{item.get('order_id')} | {item.get('status')} | user {item.get('user_id')} | "
            f"@{item.get('username') or '-'} | {item.get('created_at', '')}"
        )
    # Telegram message limit is 4096 characters.
    text = "\n".join(lines)
    for start_at in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[start_at:start_at + 3900])


async def paid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update, context):
        await update.effective_message.reply_text("فقط مدیر مجاز است. / Admin only.")
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text(
            "استفاده: /paid ORDER_ID\nUsage: /paid ORDER_ID\nاین دستور را فقط پس از بررسی دستی پرداخت اجرا کنید. / Run only after manually verifying payment."
        )
        return
    order_id = context.args[0].upper()
    orders = _load_orders()
    order = orders.get(order_id)
    if not order:
        await update.effective_message.reply_text("سفارش پیدا نشد. / Order not found.")
        return
    if order.get("status") not in ("pending", "paid", "delivery_failed"):
        await update.effective_message.reply_text(f"وضعیت سفارش قابل تحویل نیست: {order.get('status')} / Order is not deliverable.")
        return
    if not PRODUCT_FILE.is_file():
        await update.effective_message.reply_text(
            f"فایل محصول در مسیر {PRODUCT_FILE.name} پیدا نشد. پرداخت را بررسی کنید؛ فایل را اضافه و دوباره /paid را اجرا کنید.\n"
            "Product file missing. Place it beside bot.py, then retry /paid."
        )
        return
    order["status"] = "paid"
    order["paid_at"] = datetime.now(timezone.utc).isoformat()
    order["confirmed_by_admin_id"] = update.effective_user.id
    _save_orders(orders)
    try:
        with PRODUCT_FILE.open("rb") as workbook:
            await context.bot.send_document(
                chat_id=order["user_id"],
                document=workbook,
                filename=PRODUCT_FILE.name,
                caption=(f"فایل {PRODUCT_NAME} — سفارش {order_id}\n"
                         f"{PRODUCT_NAME} workbook — order {order_id}"),
            )
        order["status"] = "delivered"
        order["delivered_at"] = datetime.now(timezone.utc).isoformat()
        _save_orders(orders)
        await update.effective_message.reply_text(
            f"پرداخت دستی تأیید و فایل برای سفارش {order_id} ارسال شد.\n"
            f"Payment manually confirmed and workbook delivered for {order_id}."
        )
    except Exception:
        order["status"] = "delivery_failed"
        _save_orders(orders)
        log.exception("Delivery failed for order %s", order_id)
        await update.effective_message.reply_text(
            f"ارسال فایل ناموفق بود؛ پس از رفع مشکل دوباره /paid {order_id} را اجرا کنید.\n"
            f"Delivery failed; fix the issue and retry /paid {order_id}."
        )


def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    admin_raw = os.getenv("ADMIN_ID", "").strip()
    if not token or not admin_raw:
        raise SystemExit("Set BOT_TOKEN and ADMIN_ID environment variables (see .env.example and README.md).")
    try:
        admin_id = int(admin_raw)
    except ValueError as exc:
        raise SystemExit("ADMIN_ID must be your numeric Telegram user ID.") from exc
    if not PRODUCT_FILE.is_file():
        raise SystemExit(f"Workbook not found: {PRODUCT_FILE}. Put it beside bot.py or set PRODUCT_FILE.")
    app = Application.builder().token(token).build()
    app.bot_data["admin_id"] = admin_id
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("paid", paid_command))
    log.info("Bot starting; order data: %s", ORDERS_FILE)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
