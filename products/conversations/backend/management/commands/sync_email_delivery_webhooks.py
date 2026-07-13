from typing import Any

from django.core.management.base import BaseCommand

from products.conversations.backend.mailgun import delivery_webhook_url, sync_delivery_webhooks
from products.conversations.backend.models import EmailChannel


class Command(BaseCommand):
    help = (
        "Register Mailgun delivery-event webhooks (proof of delivery) for every verified "
        "conversations email domain. Connect/verify flows sync webhooks going forward; "
        "this backfills domains verified before delivery tracking existed."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="List domains without calling Mailgun")

    def handle(self, *args: Any, **options: Any) -> None:
        webhook_url = delivery_webhook_url()
        domains = (
            EmailChannel.objects.filter(domain_verified=True)
            .order_by("domain")
            .values_list("domain", flat=True)
            .distinct()
        )

        self.stdout.write(f"Syncing delivery webhooks for {len(domains)} domain(s) -> {webhook_url}")
        for domain in domains:
            if options["dry_run"]:
                self.stdout.write(f"would sync {domain}")
                continue
            try:
                sync_delivery_webhooks(domain, webhook_url)
                self.stdout.write(self.style.SUCCESS(f"synced {domain}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"failed {domain}: {e}"))
