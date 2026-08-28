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
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.plugins.plugin_server_api import rerun_hog_invocations

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

GOOGLE_ADS_TEMPLATE_ID = "template-google-ads"
DEFAULT_ERROR_KIND = "http_4xx"

# Matches RERUN_MAX_WINDOW_DAYS in posthog/api/hog_invocation_rerun.py, which
# is the ClickHouse TTL on hog_invocation_results. Anything past this either
# 400s downstream or silently under-replays because the partitions are gone.
MAX_WINDOW_DAYS = 30


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
        window_start = _parse_iso(options["window_start"], "window-start")
        window_end = _parse_iso(options["window_end"], "window-end")
        if window_end <= window_start:
            raise CommandError("--window-end must be after --window-start.")
        if window_end - window_start > timedelta(days=MAX_WINDOW_DAYS):
            span_days = (window_end - window_start).days
            raise CommandError(
                f"Window cannot exceed {MAX_WINDOW_DAYS} days (ClickHouse TTL on hog_invocation_results). "
                f"Got {span_days} days."
            )

        error_kinds = options["error_kind"] or [DEFAULT_ERROR_KIND]
        dry_run: bool = options["dry_run"]
        sleep_seconds: float = options["sleep_seconds"]
        max_count: int | None = options.get("max_count")
        team_ids: list[int] | None = options.get("team_ids")

        qs = HogFunction.objects.filter(
            template_id=GOOGLE_ADS_TEMPLATE_ID,
            type="destination",
            enabled=True,
            deleted=False,
        ).select_related("team")
        if team_ids:
            qs = qs.filter(team_id__in=team_ids)
        qs = qs.order_by("team_id", "id")

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No active Google Ads destinations matched."))
            return

        distinct_teams = qs.values("team_id").distinct().count()
        self.stdout.write(f"Found {total} active Google Ads destinations across {distinct_teams} teams.")
        self.stdout.write(
            f"Window: {window_start.isoformat()} → {window_end.isoformat()}   "
            f"error_kind={error_kinds}   status=[failed]"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no rerun requests will be sent."))

        filter_payload: dict[str, Any] = {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "status": ["failed"],
            "error_kind": error_kinds,
        }
        if max_count is not None:
            filter_payload["max_count"] = max_count
        payload = {"filter": filter_payload}

        started = time.time()
        enqueued = 0
        failures: list[tuple[int, str, int, str]] = []  # (team_id, function_id, status, message)
        status_counts: dict[int, int] = {}

        for fn in qs.iterator(chunk_size=200):
            team_id = fn.team_id
            org_id = fn.team.organization_id if fn.team_id else None
            fn_id = str(fn.id)
            label = f"team={team_id} org={org_id} function={fn_id} ({fn.name!r})"

            if dry_run:
                self.stdout.write(f"  [dry-run] would rerun {label}")
                enqueued += 1
                continue

            try:
                res = rerun_hog_invocations(
                    team_id=team_id,
                    function_kind="hog_function",
                    function_id=fn_id,
                    payload=payload,
                )
            except Exception as e:
                failures.append((team_id, fn_id, 0, f"exception: {e!r}"))
                status_counts[0] = status_counts.get(0, 0) + 1
                self.stdout.write(self.style.ERROR(f"  ✗ {label}: exception {e!r}"))
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
                continue

            status_counts[res.status_code] = status_counts.get(res.status_code, 0) + 1

            if res.status_code != 200:
                failures.append((team_id, fn_id, res.status_code, res.text[:200]))
                self.stdout.write(self.style.ERROR(f"  ✗ {label}: HTTP {res.status_code}: {res.text[:200]}"))
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
                continue

            try:
                body = res.json()
            except ValueError:
                body = {}
            rerun_job_id = body.get("rerun_job_id", "?")
            enqueued += 1
            self.stdout.write(f"  ✓ {label}: rerun_job_id={rerun_job_id}")

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        duration = time.time() - started
        enqueued_label = "WouldEnqueue" if dry_run else "Enqueued"
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done in {duration:.1f}s. Destinations={total} | {enqueued_label}={enqueued} | Failed={len(failures)}"
            )
        )
        if status_counts:
            breakdown = ", ".join(f"{code}: {count}" for code, count in sorted(status_counts.items()))
            self.stdout.write(f"HTTP status breakdown: {breakdown}")
        if failures:
            self.stdout.write(self.style.WARNING(f"{len(failures)} rerun request(s) failed:"))
            for team_id, fn_id, status_code, msg in failures:
                self.stdout.write(f"  team={team_id} function={fn_id} status={status_code} :: {msg}")


def _parse_iso(raw: str, arg_name: str) -> datetime:
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as e:
        raise CommandError(f"--{arg_name}: could not parse ISO-8601 datetime {raw!r}: {e}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
