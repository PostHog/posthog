"""
Trigger reruns of failed invocations for every active Google Ads
destination across every team.

Written for the 2026-07-02 incident where Google Ads returned 401
UNAUTHENTICATED (`DEVELOPER_TOKEN_INVALID`) for every send, surfaced on
our side as `error_kind='http_4xx'`. Once operators have swapped the
developer token, this replays the failed sends by triggering the same
"Rerun failed invocations" action the UI's Runs tab would trigger —
scoped to `status=failed` and `error_kind=http_4xx` — for each affected
hog function.

Reruns run asynchronously on `cdp-rerun-worker`; this command only
enqueues one wrapper job per hog function and reports which teams they
were enqueued for.
"""

import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, QuerySet

from posthog.api.hog_invocation_rerun import RERUN_MAX_WINDOW_DAYS
from posthog.dataclasses import frozen
from posthog.plugins.plugin_server_api import rerun_hog_invocations
from posthog.utils import ensure_utc

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

GOOGLE_ADS_TEMPLATE_ID = "template-google-ads"
DEFAULT_ERROR_KIND = "http_4xx"

# The ClickHouse TTL on hog_invocation_results. A longer window either 400s
# downstream or silently under-replays because the partitions are gone.
MAX_WINDOW_DAYS = RERUN_MAX_WINDOW_DAYS


@frozen
class RerunWindow:
    start: datetime
    end: datetime


@frozen
class RerunResult:
    team_id: int
    function_id: str
    status_code: int
    error: str | None


def _parse_iso(raw: str, arg_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as e:
        raise CommandError(f"--{arg_name}: could not parse ISO-8601 datetime {raw!r}: {e}")
    return ensure_utc(parsed).astimezone(UTC)


def _parse_window(options: dict[str, Any]) -> RerunWindow:
    start = _parse_iso(options["window_start"], "window-start")
    end = _parse_iso(options["window_end"], "window-end")
    if end <= start:
        raise CommandError("--window-end must be after --window-start.")
    if end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise CommandError(
            f"Window cannot exceed {MAX_WINDOW_DAYS} days (ClickHouse TTL on hog_invocation_results). "
            f"Got {(end - start).days} days."
        )
    return RerunWindow(start=start, end=end)


def _active_google_ads_destinations(team_ids: list[int] | None) -> QuerySet[HogFunction]:
    qs = HogFunction.objects.filter(
        template_id=GOOGLE_ADS_TEMPLATE_ID,
        type="destination",
        enabled=True,
        deleted=False,
    ).select_related("team")
    if team_ids:
        qs = qs.filter(team_id__in=team_ids)
    return qs.order_by("team_id", "id")


def _build_payload(window: RerunWindow, error_kinds: list[str], max_count: int | None) -> dict[str, Any]:
    filter_payload: dict[str, Any] = {
        "window_start": window.start.isoformat(),
        "window_end": window.end.isoformat(),
        "status": ["failed"],
        "error_kind": error_kinds,
    }
    if max_count is not None:
        filter_payload["max_count"] = max_count
    return {"filter": filter_payload}


def _label(fn: HogFunction) -> str:
    org_id = fn.team.organization_id if fn.team_id else None
    return f"team={fn.team_id} org={org_id} function={fn.id} ({fn.name!r})"


class Command(BaseCommand):
    help = (
        "Rerun failed invocations for every active Google Ads destination. "
        "Filters by status=failed + --error-kind (default http_4xx). Prints "
        "per-function results and a summary."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-start",
            required=True,
            help="Inclusive ISO-8601 UTC lower bound (e.g. 2026-07-02T00:00:00Z).",
        )
        parser.add_argument(
            "--window-end",
            required=True,
            help="Exclusive ISO-8601 UTC upper bound. Max 30d window (ClickHouse TTL on hog_invocation_results).",
        )
        parser.add_argument(
            "--error-kind",
            action="append",
            default=None,
            help=f"Repeatable. Default: [{DEFAULT_ERROR_KIND}].",
        )
        parser.add_argument(
            "--max-count",
            type=int,
            default=None,
            help="Per-function cap. Server-side hard cap still applies.",
        )
        parser.add_argument(
            "--team-ids",
            nargs="+",
            type=int,
            default=None,
            help="Restrict to specific team IDs (default: every team with an active Google Ads destination).",
        )
        parser.add_argument(
            "--sleep-seconds",
            type=float,
            default=0.0,
            help="Delay between rerun requests. Spreads load if rerun queue depth spikes.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List which hog functions would be rerun without triggering the reruns.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        window = _parse_window(options)
        error_kinds = options["error_kind"] or [DEFAULT_ERROR_KIND]
        dry_run: bool = options["dry_run"]
        sleep_seconds: float = options["sleep_seconds"]

        qs = _active_google_ads_destinations(options.get("team_ids"))
        counts = qs.aggregate(total=Count("id"), teams=Count("team_id", distinct=True))
        total: int = counts["total"]
        if total == 0:
            self.stdout.write(self.style.WARNING("No active Google Ads destinations matched."))
            return

        self._write_header(total, counts["teams"], window, error_kinds, dry_run)
        payload = _build_payload(window, error_kinds, options.get("max_count"))

        started = time.time()
        enqueued = 0
        results: list[RerunResult] = []

        for fn in qs.iterator(chunk_size=200):
            if dry_run:
                self.stdout.write(f"  [dry-run] would rerun {_label(fn)}")
                enqueued += 1
                continue

            result = self._rerun_one(fn, payload)
            results.append(result)
            if result.error is None:
                enqueued += 1

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        self._write_summary(
            duration=time.time() - started,
            total=total,
            enqueued=enqueued,
            results=results,
            dry_run=dry_run,
        )

    def _rerun_one(self, fn: HogFunction, payload: dict[str, Any]) -> RerunResult:
        label = _label(fn)
        fn_id = str(fn.id)
        try:
            res = rerun_hog_invocations(
                team_id=fn.team_id,
                function_kind="hog_function",
                function_id=fn_id,
                payload=payload,
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ✗ {label}: exception {e!r}"))
            return RerunResult(team_id=fn.team_id, function_id=fn_id, status_code=0, error=f"exception: {e!r}")

        if res.status_code != 200:
            message = res.text[:200]
            self.stdout.write(self.style.ERROR(f"  ✗ {label}: HTTP {res.status_code}: {message}"))
            return RerunResult(team_id=fn.team_id, function_id=fn_id, status_code=res.status_code, error=message)

        try:
            body = res.json()
        except ValueError:
            body = {}
        self.stdout.write(f"  ✓ {label}: rerun_job_id={body.get('rerun_job_id', '?')}")
        return RerunResult(team_id=fn.team_id, function_id=fn_id, status_code=res.status_code, error=None)

    def _write_header(
        self,
        total: int,
        distinct_teams: int,
        window: RerunWindow,
        error_kinds: list[str],
        dry_run: bool,
    ) -> None:
        self.stdout.write(f"Found {total} active Google Ads destinations across {distinct_teams} teams.")
        self.stdout.write(
            f"Window: {window.start.isoformat()} → {window.end.isoformat()}   "
            f"error_kind={error_kinds}   status=[failed]"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no rerun requests will be sent."))

    def _write_summary(
        self,
        *,
        duration: float,
        total: int,
        enqueued: int,
        results: list[RerunResult],
        dry_run: bool,
    ) -> None:
        failures = [result for result in results if result.error is not None]
        enqueued_label = "WouldEnqueue" if dry_run else "Enqueued"
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done in {duration:.1f}s. Destinations={total} | {enqueued_label}={enqueued} | Failed={len(failures)}"
            )
        )
        if results:
            status_counts = Counter(result.status_code for result in results)
            breakdown = ", ".join(f"{code}: {count}" for code, count in sorted(status_counts.items()))
            self.stdout.write(f"HTTP status breakdown: {breakdown}")
        if failures:
            self.stdout.write(self.style.WARNING(f"{len(failures)} rerun request(s) failed:"))
            for failure in failures:
                self.stdout.write(
                    f"  team={failure.team_id} function={failure.function_id} "
                    f"status={failure.status_code} :: {failure.error}"
                )
