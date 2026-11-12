"""Resend a weekly digest to chosen organizations from the data the scheduled run already generated.

The digest data stays in the digest Redis for three days after the scheduled run, so resend within that window.

Usage:
    # Resend to organizations a failed send skipped. Members who already got it get a second copy.
    python manage.py resend_weekly_digest --digest-key weekly-digest-2026-45 --org <uuid> --org <uuid>

    # Log who would get the digest, without sending
    python manage.py resend_weekly_digest --digest-key weekly-digest-2026-45 --org <uuid> --dry-run
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.temporal.common.client import async_connect
from posthog.temporal.weekly_digest.types import WeeklyDigestInput

DIGEST_KEY_PREFIX = "weekly-digest-"


def period_end_for_digest_key(digest_key: str) -> datetime:
    # The scheduled run names its key after the ISO week of its Monday, and its period ends at that Monday's midnight.
    try:
        year, week = (int(part) for part in digest_key.removeprefix(DIGEST_KEY_PREFIX).split("-"))
        monday = datetime.fromisocalendar(year, week, 1)
    except ValueError as err:
        raise CommandError(f"Expected a digest key like {DIGEST_KEY_PREFIX}2026-45, got {digest_key!r}") from err
    return monday.replace(tzinfo=UTC)


class Command(BaseCommand):
    help = "Resend a weekly digest to chosen organizations from the data the scheduled run already generated."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--digest-key", required=True, help="Key of the scheduled run to resend, such as weekly-digest-2026-45."
        )
        parser.add_argument(
            "--org",
            dest="organization_ids",
            action="append",
            required=True,
            type=UUID,
            help="Organization (UUID) to resend to. Repeat the option for more organizations.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Log who would get the digest without sending it.")

    def handle(self, *args: Any, **options: Any) -> None:
        digest_key: str = options["digest_key"]
        organization_ids = [str(organization_id) for organization_id in options["organization_ids"]]
        workflow_input = WeeklyDigestInput(
            dry_run=options["dry_run"],
            skip_generate=True,
            digest_key_override=digest_key,
            # The scheduled run marks every organization it reached as sent, including ones a failure cut short.
            allow_already_sent=True,
            organization_ids=organization_ids,
            period_end_override=period_end_for_digest_key(digest_key),
        )
        workflow_id = f"weekly-digest-resend-{digest_key}-{uuid4()}"
        asyncio.run(self._start(workflow_input, workflow_id))
        self.stdout.write(
            self.style.SUCCESS(
                f"Started {workflow_id} for {len(organization_ids)} organization(s). Follow it in the Temporal UI."
            )
        )

    async def _start(self, workflow_input: WeeklyDigestInput, workflow_id: str) -> None:
        client = await async_connect()
        await client.start_workflow(
            "weekly-digest", workflow_input, id=workflow_id, task_queue=settings.WEEKLY_DIGEST_TASK_QUEUE
        )
