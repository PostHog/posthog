"""Run social-referral-status ingestion sync in-process (no Temporal worker).

Mirrors the ``social-referral-status`` Temporal workflow: for each pending
``SocialReferral`` row, flip ``first_event_sent`` when the referee org's team has
``ingested_event``, issue Shopify referrer codes when configured, and send the
merch coupon email over SMTP for every flipped referee (no code in body; Shopify optional).

Examples::

    python manage.py run_social_referral_status_sync
    python manage.py run_social_referral_status_sync --social-referral-id <uuid>
    python manage.py run_social_referral_status_sync --test
"""

from __future__ import annotations

import uuid
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.email import EmailMessage

from products.referrals.backend.temporal.activities import (
    execute_referral_ingestion_stage_sweep,
    process_single_social_referral_ingestion_sync,
)

_TEST_RECIPIENT_EMAIL = "test@posthog.com"
_TEST_DISCOUNT_CODE = "REFERRAL-YC2F7D"
_TEST_REFEREE_ORG_NAME = "PostHog Test Org"


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
        parser.add_argument(
            "--test",
            action="store_true",
            help=(
                "Skip all sweep logic and just render+send the Shopify reward email to "
                f"{_TEST_RECIPIENT_EMAIL} with a hardcoded code. No DB reads or writes."
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        if options["test"]:
            self._send_test_shopify_reward_email()
            return

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

    def _send_test_shopify_reward_email(self) -> None:
        """Render the Shopify reward template with hardcoded values and SMTP-send to the test recipient.

        Builds ``EmailMessage`` directly (rather than calling ``deliver_social_referral_shopify_reward_email``)
        so there is zero DB activity — no ``User.objects.get`` lookup, no campaign-key dedup row write,
        no scope audit. Matches the template context shape of the real deliver function so the rendered
        email is representative.
        """
        self.stdout.write(f"Recipient:        {_TEST_RECIPIENT_EMAIL}")
        self.stdout.write(f"Discount code:    {_TEST_DISCOUNT_CODE}")
        self.stdout.write(f"Referee org:      {_TEST_REFEREE_ORG_NAME}")
        self.stdout.write("")

        message = EmailMessage(
            use_http=False,
            campaign_key=f"social-referral-shopify-test-{uuid.uuid4()}",
            subject="Your PostHog merch coupon — thanks for the referral",
            template_name="social_referral_shopify_reward",
            template_context={
                "preheader": f"Your merch coupon {_TEST_DISCOUNT_CODE} is ready.",
                "user_name": "there",
                "discount_code": _TEST_DISCOUNT_CODE,
                "referee_organization_name": _TEST_REFEREE_ORG_NAME,
                "cloud": False,
                "site_url": settings.SITE_URL or "",
                "referrals_path": "/referrals",
            },
        )
        message.add_recipient(email=_TEST_RECIPIENT_EMAIL)
        message.send(send_async=False)
        self.stdout.write(self.style.SUCCESS(f"Sent Shopify reward test email to {_TEST_RECIPIENT_EMAIL}"))
