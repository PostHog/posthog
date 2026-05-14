"""Run social-referral-status ingestion sync in-process (no Temporal worker).

Mirrors the ``social-referral-status`` Temporal workflow: for each pending
``SocialReferral`` row, flip ``first_event_sent`` when the referee org's team has
``ingested_event``, issue Shopify referrer codes when configured, and send the
merch coupon email over SMTP for every flipped referee (no code in body; Shopify optional).

Examples::

    python manage.py run_social_referral_status_sync
    python manage.py run_social_referral_status_sync --social-referral-id <uuid>
"""

from __future__ import annotations

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from products.referrals.backend.temporal.activities import (
    execute_referral_ingestion_stage_sweep,
    process_single_social_referral_ingestion_sync,
)


class Command(BaseCommand):
    help = "Run social referral referee ingestion sync (same logic as social-referral-status Temporal workflow)"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--social-referral-id",
            type=str,
            default="",
            metavar="UUID",
            help="Only process this SocialReferral row (default: full sweep of pending referrals)",
        )

    def handle(self, *args: object, **options: object) -> None:
        social_referral_id = str(options["social_referral_id"] or "")
        if social_referral_id:
            try:
                rid = UUID(social_referral_id)
            except ValueError as e:
                raise CommandError(f"Invalid --social-referral-id: {social_referral_id!r}") from e
            result = process_single_social_referral_ingestion_sync(rid)
            self.stdout.write(self.style.SUCCESS(f"Processed SocialReferral {rid}: {result!r}"))
            return

        summary = execute_referral_ingestion_stage_sweep()
        self.stdout.write(self.style.SUCCESS(f"Social referral ingestion sweep finished: {summary!r}"))
