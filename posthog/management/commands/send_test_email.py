"""
Send a minimal SMTP message for local Maildev / Mailpit testing.

Uses the same EMAIL_* instance settings as production SMTP paths but skips Celery,
templates, and MessagingRecord.

Example:
    python manage.py send_test_email dev@example.com
    python manage.py send_test_email --subject "Hello" --body "Plain text only"
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend
from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from posthog.models.instance_setting import get_instance_setting


class Command(BaseCommand):
    help = "Send a simple SMTP email for local email trap testing (Maildev on 1025 / web UI 1080)"

    def add_arguments(self, parser):
        parser.add_argument(
            "to",
            nargs="?",
            default="test@example.com",
            help="Recipient address (default: test@example.com)",
        )
        parser.add_argument("--subject", default="PostHog local email test")
        parser.add_argument(
            "--body",
            default="If this appears in your local SMTP trap, Django SMTP is wired correctly.",
        )
        parser.add_argument(
            "--html",
            default="",
            help="Optional HTML body (sent as multipart/alternative alongside --body)",
        )

    def handle(self, **options) -> None:
        to_addr: str = options["to"]
        subject: str = options["subject"]
        body: str = options["body"]
        html_body: str = options["html"] or ""

        if not get_instance_setting("EMAIL_ENABLED"):
            raise CommandError("EMAIL_ENABLED is false. Set EMAIL_ENABLED=true in your environment for local testing.")
        if not get_instance_setting("EMAIL_HOST"):
            raise CommandError(
                "EMAIL_HOST is unset. For Maildev use EMAIL_HOST=127.0.0.1 and EMAIL_PORT=1025 "
                "(see docs/published/handbook/engineering/developing-locally.md)."
            )

        from_email = get_instance_setting("EMAIL_DEFAULT_FROM")
        reply_to_raw = get_instance_setting("EMAIL_REPLY_TO")
        reply_to_kw = [reply_to_raw] if reply_to_raw else None

        klass = import_string(settings.EMAIL_BACKEND) if settings.EMAIL_BACKEND else EmailBackend
        connection = klass(
            host=get_instance_setting("EMAIL_HOST"),
            port=get_instance_setting("EMAIL_PORT"),
            username=get_instance_setting("EMAIL_HOST_USER"),
            password=get_instance_setting("EMAIL_HOST_PASSWORD"),
            use_tls=get_instance_setting("EMAIL_USE_TLS"),
            use_ssl=get_instance_setting("EMAIL_USE_SSL"),
        )

        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[to_addr],
            reply_to=reply_to_kw,
        )
        if html_body:
            message.attach_alternative(html_body, "text/html")

        host = get_instance_setting("EMAIL_HOST")
        port = get_instance_setting("EMAIL_PORT")
        self.stdout.write(f"Sending to {to_addr} via SMTP {host}:{port} …")

        try:
            connection.open()
            connection.send_messages([message])
        except Exception as exc:
            raise CommandError(f"SMTP send failed: {exc}") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS(f"Sent test email to {to_addr}"))
