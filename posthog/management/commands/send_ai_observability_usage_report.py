from typing import Any

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

import structlog
from dateutil import parser

from posthog.tasks.ai_observability_usage_report import (
    USAGE_REPORT_DISPATCH_LOCK_TIMEOUT_SECONDS,
    send_ai_observability_usage_reports,
    usage_report_dispatch_lock_key,
)

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Send the AI observability usage report for a given day"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Print information instead of sending it")
        parser.add_argument("--date", type=str, help="The date to be run in format YYYY-MM-DD")
        parser.add_argument("--async", action="store_true", help="Run the task asynchronously")
        parser.add_argument(
            "--org-ids",
            type=str,
            help="Comma-separated list of organization UUIDs to process (e.g., 'uuid1,uuid2,uuid3')",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        date = self._normalized_date(options["date"])
        run_async = options["async"]
        org_ids_str = options.get("org_ids")

        organization_ids = (
            ([oid.strip() for oid in org_ids_str.split(",") if oid.strip()] or None) if org_ids_str else None
        )

        # The task's already-reported lookup cannot see an emission that has not been ingested yet,
        # so it does not stop two dispatches made seconds apart. Claiming the date here does, because
        # the claim is atomic. A dry run emits nothing, so it must not claim and lock out a real run.
        if not dry_run:
            self._claim_dispatch(date)

        # Both branches release the claim when the call raises. The task emits nothing before it can
        # raise: it fails in the feature-flag check, the already-reported lookup, or the gathering, all
        # of which precede the emission loop, and the loop itself swallows and logs per-organization
        # failures rather than propagating them. Holding the claim after such a failure would lock the
        # date out while nothing had been emitted, and there is no way to clear it by hand.
        #
        # `Exception` rather than `BaseException` on purpose. Ctrl+C raises `KeyboardInterrupt`, which
        # a synchronous run can take part way through the emission loop, once some organizations
        # already have reports. Releasing the claim there would admit a second run that cannot yet see
        # those emissions, so an interrupt deliberately keeps the date claimed until the claim expires.
        try:
            if run_async:
                send_ai_observability_usage_reports.delay(
                    dry_run=dry_run,
                    at=date,
                    organization_ids=organization_ids,
                )
                print("Queued!")  # noqa: T201
            else:
                send_ai_observability_usage_reports(
                    dry_run=dry_run,
                    at=date,
                    organization_ids=organization_ids,
                )

                if dry_run:
                    print("Dry run so not sent.")  # noqa: T201
                elif organization_ids:
                    print(f"Done! Processed {len(organization_ids)} organization(s).")  # noqa: T201
                else:
                    print("Done!")  # noqa: T201
        except Exception:
            if not dry_run:
                self._release_dispatch(date)
            raise

    def _normalized_date(self, date: str | None) -> str:
        """The report date as `YYYY-MM-DD`, defaulting to today.

        The task resolves this with `dateutil`, which reads `2026-08-01`, `2026-8-1` and `08/01/2026`
        as the same day, while the claim key is a literal string. Without normalizing first, those
        spellings take different claims for one date and both runs emit. Normalizing here also turns
        an unparseable date into an immediate error rather than one raised later inside a worker.
        """
        if not date:
            return timezone.now().date().isoformat()

        try:
            return parser.parse(date).date().isoformat()
        except (ValueError, OverflowError) as e:
            raise CommandError(f"Could not read '{date}' as a date. Use the format YYYY-MM-DD.") from e

    def _claim_dispatch(self, date: str) -> None:
        """Claim `date` for this dispatch, refusing when another dispatch already holds it.

        `cache.add` only writes when the key is absent, so concurrent dispatches race on the write
        itself and exactly one wins. The claim is never released on success: releasing it before the
        emitted events are queryable would reopen the window it exists to close.
        """
        if not cache.add(usage_report_dispatch_lock_key(date), "1", timeout=USAGE_REPORT_DISPATCH_LOCK_TIMEOUT_SECONDS):
            raise CommandError(
                f"A usage report run for {date} was already dispatched and may still be emitting. "
                f"The claim covers the whole date, including runs scoped to specific organizations. "
                f"Wait for that run to finish, then dispatch again to cover any organization it missed."
            )

    def _release_dispatch(self, date: str) -> None:
        """Release the claim on `date`, without letting a cache failure replace the caller's error."""
        try:
            cache.delete(usage_report_dispatch_lock_key(date))
        except Exception:
            logger.warning(
                "Could not release the AI observability usage report dispatch claim",
                date=date,
                exc_info=True,
            )
