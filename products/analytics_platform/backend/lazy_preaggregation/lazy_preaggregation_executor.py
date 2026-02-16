import copy
import json
import time
import uuid
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone as django_timezone

import redis as redis_lib
from clickhouse_driver.errors import ServerException

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE
from posthog.clickhouse.query_tagging import tags_context
from posthog.models.team import Team
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.utils import relative_date_parse_with_delta_mapping

from products.analytics_platform.backend.lazy_preaggregation.preaggregation_notifications import (
    has_ch_query_started,
    is_ch_query_alive,
    job_channel,
    publish_job_completion,
    set_ch_query_started,
    subscribe_to_jobs,
)
from products.analytics_platform.backend.models import PreaggregationJob

# Default TTL for preaggregated data (how long before ClickHouse deletes it)
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# ClickHouse data outlives the PG job by this amount. This prevents races where we fetch a job in PG, use it, but while
# waiting for something else, it expires and is deleted in clickhouse.
EXPIRY_BUFFER_SECONDS = 1 * 60 * 60  # 1 hour

# Waiting configuration for pending jobs
DEFAULT_WAIT_TIMEOUT_SECONDS = 180  # 3 minutes
DEFAULT_POLL_INTERVAL_SECONDS = 1.0  # Initial poll interval (doubles each iteration)
DEFAULT_MAX_POLL_INTERVAL_SECONDS = 30.0  # Cap for exponential backoff
DEFAULT_RETRIES = 1  # Maximum retry attempts for failed jobs

# How long to wait for another executor to insert a job, before we assume it has failed.
# With CH heartbeat liveness, this mainly covers the gap between CH start marker and
# poll_query_performance first picking it up (~2-4 seconds). Conservative default.
DEFAULT_STALE_PENDING_THRESHOLD_SECONDS = 60  # 1 minute

# Grace period before declaring a job "not started" as stale. Covers executor boot time.
DEFAULT_CH_START_GRACE_PERIOD_SECONDS = 60  # 1 minute


@dataclass
class TtlSchedule:
    """Maps time windows to TTL values based on their recency.

    Rules are (cutoff_datetime, ttl_seconds) pairs sorted by cutoff descending.
    A window matches the first rule where window_start >= cutoff. If no rule
    matches, default_ttl_seconds is used.

    Use parse_ttl_schedule() to create from user-facing dict format.
    """

    rules: list[tuple[datetime, int]]
    default_ttl_seconds: int

    def get_ttl(self, window_start: datetime) -> int:
        for cutoff, ttl in self.rules:
            if window_start >= cutoff:
                return ttl
        return self.default_ttl_seconds

    @classmethod
    def from_seconds(cls, ttl_seconds: int) -> "TtlSchedule":
        return cls(rules=[], default_ttl_seconds=ttl_seconds)


DEFAULT_TTL_SCHEDULE = TtlSchedule.from_seconds(DEFAULT_TTL_SECONDS)


def parse_ttl_schedule(
    ttl: int | dict[str, int],
    team_timezone: str = "UTC",
) -> TtlSchedule:
    """Parse a TTL specification into a TtlSchedule.

    Accepts either:
    - int: uniform TTL in seconds for all ranges
    - dict: maps date strings to TTL values in seconds. Keys are parsed using
      relative_date_parse (e.g. "7d" = 7 days ago, "24h" = 24 hours ago,
      "2026-02-15" = exact date). The "default" key sets the fallback TTL.

    Rules are evaluated most-recent-first: the first matching rule wins. For
    example, {"0d": 900, "7d": 86400, "default": 604800} means today's data
    gets 15 min TTL, last week gets 1 day, everything else gets 7 days.

    Raises ValueError for unrecognized keys or non-positive TTL values.
    """
    if isinstance(ttl, int):
        if ttl <= 0:
            raise ValueError(f"TTL must be positive, got {ttl}")
        return TtlSchedule.from_seconds(ttl)

    tz = ZoneInfo(team_timezone)
    rules: list[tuple[datetime, int]] = []
    default_ttl = DEFAULT_TTL_SECONDS

    for key, value in ttl.items():
        if value <= 0:
            raise ValueError(f"TTL value for key {key!r} must be positive, got {value}")
        if key == "default":
            default_ttl = value
        else:
            cutoff, delta_mapping, _ = relative_date_parse_with_delta_mapping(key, tz, always_truncate=True)
            # delta_mapping is None for ISO dates, non-empty for valid relative dates
            # (e.g. "7d" → {"days": 7}), and empty for unrecognized input
            if delta_mapping is not None and not delta_mapping:
                raise ValueError(
                    f"Unrecognized TTL schedule key: {key!r}. "
                    "Use relative dates (e.g. '7d', '24h'), ISO dates (e.g. '2026-02-15'), or 'default'."
                )
            rules.append((cutoff, value))

    rules.sort(key=lambda r: r[0], reverse=True)
    return TtlSchedule(rules=rules, default_ttl_seconds=default_ttl)


def split_ranges_by_ttl(
    ranges: list[tuple[datetime, datetime]],
    schedule: TtlSchedule,
) -> list[tuple[datetime, datetime, int]]:
    """Split time ranges at TTL boundaries.

    Re-expands each range into daily windows, assigns a TTL per window, and
    merges consecutive windows with the same TTL. This prevents a single job
    from covering days with different TTL requirements.
    """
    result: list[tuple[datetime, datetime, int]] = []

    for range_start, range_end in ranges:
        windows = get_daily_windows(range_start, range_end)
        if not windows:
            continue

        current_start, current_end = windows[0]
        current_ttl = schedule.get_ttl(current_start)

        for window_start, window_end in windows[1:]:
            ttl = schedule.get_ttl(window_start)
            if ttl == current_ttl:
                current_end = window_end
            else:
                result.append((current_start, current_end, current_ttl))
                current_start, current_end = window_start, window_end
                current_ttl = ttl

        result.append((current_start, current_end, current_ttl))

    return result


# ClickHouse error codes that should NOT be retried.
# These are errors where retrying will never help - the query itself is broken,
# or the user needs to change something about their request.
NON_RETRYABLE_CLICKHOUSE_ERROR_CODES = {
    62,  # SYNTAX_ERROR
    43,  # ILLEGAL_TYPE_OF_ARGUMENT
    53,  # TYPE_MISMATCH
    46,  # UNKNOWN_FUNCTION
    47,  # UNKNOWN_IDENTIFIER
    60,  # UNKNOWN_TABLE
    16,  # NO_SUCH_COLUMN_IN_TABLE
    # Timeout means the query is too expensive - retrying won't help,
    # and we want to surface this to the user so they can adjust their query.
    159,  # TIMEOUT_EXCEEDED
    # Too many simultaneous queries means the cluster is overloaded.
    # Rather than adding to the load with retries, surface the error.
    202,  # TOO_MANY_SIMULTANEOUS_QUERIES
}


RESERVED_PLACEHOLDERS = {"time_window_min", "time_window_max"}


def _validate_no_reserved_placeholders(placeholders: dict[str, ast.Expr]) -> None:
    conflicting = RESERVED_PLACEHOLDERS & set(placeholders)
    if conflicting:
        raise ValueError(
            f"Cannot use reserved placeholder names: {conflicting}. "
            "time_window_min and time_window_max are automatically added per-job."
        )


def is_non_retryable_error(error: Exception) -> bool:
    """
    Check if an error should NOT be retried.

    Non-retryable errors are those where the query itself is invalid or the
    cluster is overloaded - retrying won't help and may make things worse.

    Transient errors (network issues, connection drops) are retryable since
    the server may recover.

    Walks the exception __cause__ chain to check wrapped errors (e.g., from wrap_query_error).
    """
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ServerException) and current.code in NON_RETRYABLE_CLICKHOUSE_ERROR_CODES:
            return True
        current = current.__cause__
    return False


class PreaggregationTable(StrEnum):
    """Allowed target tables for preaggregation results."""

    PREAGGREGATION_RESULTS = "preaggregation_results"
    EXPERIMENT_EXPOSURES_PREAGGREGATED = "experiment_exposures_preaggregated"


# Tables where expires_at is a Date (not DateTime64). Date truncates to midnight,
# so an expires_at just after midnight would round down to a time *before* the PG
# job expires. We add an extra day of buffer for these tables.
_DATE_EXPIRES_AT_TABLES: set[PreaggregationTable] = {
    PreaggregationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
}


def _get_ch_expires_at(job: "PreaggregationJob", table: PreaggregationTable) -> datetime:
    """Compute the ClickHouse expires_at for a job, accounting for the table's column type."""
    assert job.expires_at is not None
    extra_days = 1 if table in _DATE_EXPIRES_AT_TABLES else 0
    return job.expires_at + timedelta(seconds=EXPIRY_BUFFER_SECONDS, days=extra_days)


@dataclass
class QueryInfo:
    """Normalized query information for preaggregation matching."""

    query: ast.SelectQuery
    table: PreaggregationTable
    timezone: str = "UTC"
    breakdown_fields: list[str] = field(default_factory=list)


@dataclass
class PreaggregationResult:
    """Result of executing preaggregation jobs."""

    ready: bool
    job_ids: list[uuid.UUID]
    errors: list[str] = field(default_factory=list)


def compute_query_hash(query_info: QueryInfo) -> str:
    """
    Compute a stable hash for a QueryInfo object.
    The hash is based on the normalized query structure and timezone.
    """
    # Use repr() to get a deterministic string representation of the AST
    query_str = repr(query_info.query)

    # Include timezone and breakdown fields in the hash
    # Timezone matters because toStartOfDay uses the team timezone
    hash_input = json.dumps(
        {
            "query": query_str,
            "timezone": query_info.timezone,
            "breakdown_fields": sorted(query_info.breakdown_fields),
        },
        sort_keys=True,
    )

    return hashlib.sha256(hash_input.encode()).hexdigest()


def get_daily_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """
    Generate daily time windows between start and end.
    Each window is [day_start, day_start + 1 day).
    """
    windows = []

    # Normalize to start of day in UTC
    current = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_normalized = datetime(end.year, end.month, end.day, tzinfo=UTC)

    # If end has non-zero time (e.g., 23:59:59), include that day's window
    # For example: end=2025-01-02 23:59:59 should include the Jan 2 window
    if end.hour > 0 or end.minute > 0 or end.second > 0 or end.microsecond > 0:
        end_normalized = end_normalized + timedelta(days=1)

    while current < end_normalized:
        window_end = current + timedelta(days=1)
        windows.append((current, window_end))
        current = window_end

    return windows


def find_existing_jobs(
    team: Team,
    query_hash: str,
    start: datetime,
    end: datetime,
) -> list[PreaggregationJob]:
    """
    Find all existing preaggregation jobs for the given team and query hash
    that overlap with the requested time range.

    Excludes expired jobs. ClickHouse data outlives the PG job by
    EXPIRY_BUFFER_SECONDS, so queries in flight when a job expires still
    find data.
    """
    min_expires_at = django_timezone.now()

    return list(
        PreaggregationJob.objects.filter(
            team=team,
            query_hash=query_hash,
            time_range_start__lt=end,
            time_range_end__gt=start,
            status__in=[PreaggregationJob.Status.READY, PreaggregationJob.Status.PENDING],
        )
        .filter(
            # Only include jobs with expires_at far enough in the future.
            # Jobs with expires_at=NULL (legacy) are intentionally excluded.
            Q(expires_at__gte=min_expires_at)
        )
        .order_by("time_range_start")
    )


def _intervals_overlap(start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> bool:
    """Check if two half-open intervals [start1, end1) and [start2, end2) overlap."""
    return start1 < end2 and start2 < end1


def filter_overlapping_jobs(jobs: list[PreaggregationJob]) -> list[PreaggregationJob]:
    """
    Filter out overlapping jobs, keeping only the most recently created one in case of conflict.

    When multiple jobs have overlapping time ranges, we prefer the one with the most recent
    created_at timestamp. This ensures we use the freshest data when there are duplicates.

    Uses a greedy algorithm: sort by creation date descending, then include each job only
    if it doesn't overlap with any already-selected job.
    """
    if len(jobs) <= 1:
        return jobs

    # Sort by created_at descending (most recent first)
    sorted_jobs = sorted(jobs, key=lambda j: j.created_at, reverse=True)

    selected: list[PreaggregationJob] = []
    for job in sorted_jobs:
        if not any(
            _intervals_overlap(
                job.time_range_start,
                job.time_range_end,
                selected_job.time_range_start,
                selected_job.time_range_end,
            )
            for selected_job in selected
        ):
            selected.append(job)

    return selected


def find_missing_contiguous_windows(
    existing_jobs: list[PreaggregationJob],
    start_timestamp: datetime,
    end_timestamp: datetime,
) -> list[tuple[datetime, datetime]]:
    """
    Find which daily windows are not covered by existing READY or PENDING jobs,
    then merge contiguous missing windows into ranges.

    For example, if the range is Jan 1-4 and a job exists for Jan 2,
    this returns: [(Jan 1, Jan 2), (Jan 3, Jan 4)]

    If no jobs exist for Jan 1-4, it returns: [(Jan 1, Jan 4)]
    """
    # Step 1: Generate daily windows for the range
    daily_windows = get_daily_windows(start_timestamp, end_timestamp)

    # Step 2: Find missing daily windows
    missing = []
    for window_start, window_end in daily_windows:
        # Check if this window is covered by any READY or PENDING job
        is_covered = False
        for job in existing_jobs:
            if (
                job.status in (PreaggregationJob.Status.READY, PreaggregationJob.Status.PENDING)
                and job.time_range_start <= window_start
                and job.time_range_end >= window_end
            ):
                is_covered = True
                break
        if not is_covered:
            missing.append((window_start, window_end))

    # Step 3: Merge contiguous windows into ranges
    if not missing:
        return []

    # Sort by start time (should already be sorted, but be safe)
    sorted_windows = sorted(missing, key=lambda w: w[0])

    merged = []
    current_start, current_end = sorted_windows[0]

    for window_start, window_end in sorted_windows[1:]:
        # If this window is contiguous with the current range, extend it
        if window_start == current_end:
            current_end = window_end
        else:
            # Not contiguous, save the current range and start a new one
            merged.append((current_start, current_end))
            current_start, current_end = window_start, window_end

    # Don't forget to add the last range
    merged.append((current_start, current_end))

    return merged


def create_preaggregation_job(
    team: Team,
    query_hash: str,
    time_range_start: datetime,
    time_range_end: datetime,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> PreaggregationJob:
    """Create a new preaggregation job in PENDING status with expiry time."""
    expires_at = django_timezone.now() + timedelta(seconds=ttl_seconds)
    return PreaggregationJob.objects.create(
        team=team,
        query_hash=query_hash,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        status=PreaggregationJob.Status.PENDING,
        expires_at=expires_at,
    )


def build_preaggregation_insert_sql(
    team: Team,
    job_id: str,
    select_query: ast.SelectQuery,
    time_range_start: datetime,
    time_range_end: datetime,
    expires_at: datetime,
) -> tuple[str, dict]:
    """
    Build the INSERT ... SELECT SQL for populating preaggregation results.

    Takes a SelectQuery AST with 3 expressions (time_window_start, breakdown_value, uniq_exact_state)
    and prepends team_id and appends job_id and expires_at, then adds a date range filter to the WHERE clause.
    Returns the full SQL string ready to execute.
    """
    # Deep copy the query to avoid mutating the original
    query = copy.deepcopy(select_query)

    # Validate the query has the expected structure
    assert query.select is not None, "SelectQuery must have select expressions"
    assert len(query.select) == 3, f"SelectQuery must have exactly 3 expressions, got {len(query.select)}"

    # Prepend team_id as a constant (since we filter by team_id, it's always the same)
    team_id_expr = ast.Alias(alias="team_id", expr=ast.Constant(value=team.id))
    query.select.insert(0, team_id_expr)

    # Append job_id
    job_id_expr = ast.Alias(
        alias="job_id",
        expr=ast.Call(name="toUUID", args=[ast.Constant(value=job_id)]),
    )
    query.select.append(job_id_expr)

    # Append expires_at
    expires_at_expr = ast.Alias(
        alias="expires_at",
        expr=ast.Constant(value=expires_at),
    )
    query.select.append(expires_at_expr)

    # Build the date range filter
    date_range_filter = ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=time_range_start),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=time_range_end),
            ),
        ]
    )

    # Add date range filter to existing WHERE clause
    if query.where is not None:
        query.where = ast.And(exprs=[query.where, date_range_filter])
    else:
        query.where = date_range_filter

    # Print the SELECT query to ClickHouse SQL
    context = HogQLContext(team_id=team.id, team=team, enable_select_queries=True, limit_top_select=False)
    select_sql, _ = prepare_and_print_ast(
        query,
        context=context,
        dialect="clickhouse",
    )

    sql = f"""INSERT INTO {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()} (
    team_id,
    time_window_start,
    breakdown_value,
    uniq_exact_state,
    job_id,
    expires_at
)
{select_sql}"""

    return sql, context.values


def run_preaggregation_insert(
    team: Team,
    job: PreaggregationJob,
    query_info: QueryInfo,
) -> None:
    """Run the INSERT query to populate preaggregation results in ClickHouse."""
    ch_expires_at = _get_ch_expires_at(job, PreaggregationTable.PREAGGREGATION_RESULTS)

    insert_sql, values = build_preaggregation_insert_sql(
        team=team,
        job_id=str(job.id),
        select_query=query_info.query,
        time_range_start=job.time_range_start,
        time_range_end=job.time_range_end,
        expires_at=ch_expires_at,
    )

    set_ch_query_started(job.id)
    with tags_context(client_query_id=str(job.id), team_id=team.id):
        sync_execute(
            insert_sql,
            values,
            settings={
                "max_execution_time": HOGQL_INCREASED_MAX_EXECUTION_TIME,
                **HogQLQuerySettings(load_balancing="in_order").model_dump(exclude_none=True),
            },
        )


class PreaggregationExecutor:
    """
    Executes preaggregation jobs with configurable waiting behavior.

    When a PENDING job already exists for a requested range, the executor always
    waits for it rather than creating a duplicate. This is enforced by a partial
    unique index that prevents multiple PENDING jobs for the same range.

    Uses Redis pubsub for instant job completion notifications (no PG polling).
    Stale detection checks ClickHouse query liveness via poll_query_performance heartbeats.

    Settings can be configured at initialization:
    - wait_timeout_seconds: Max time to wait for pending jobs (default 180s)
    - poll_interval_seconds: Initial poll interval, doubles each iteration (default 1s)
    - max_poll_interval_seconds: Cap for exponential backoff (default 30s)
    - max_retries: Max retries for failed jobs (default 1, meaning 2 total attempts)
    - ttl_schedule: TtlSchedule controlling how long preaggregated data persists per time range
    - stale_pending_threshold_seconds: How long before a PENDING job is considered stale
    - ch_start_grace_period_seconds: Grace period before declaring "not started" as stale
    """

    def __init__(
        self,
        wait_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_poll_interval_seconds: float = DEFAULT_MAX_POLL_INTERVAL_SECONDS,
        max_retries: int = DEFAULT_RETRIES,
        ttl_schedule: TtlSchedule = DEFAULT_TTL_SCHEDULE,
        stale_pending_threshold_seconds: float = DEFAULT_STALE_PENDING_THRESHOLD_SECONDS,
        ch_start_grace_period_seconds: float = DEFAULT_CH_START_GRACE_PERIOD_SECONDS,
    ):
        self.wait_timeout_seconds = wait_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_poll_interval_seconds = max_poll_interval_seconds
        self.max_retries = max_retries
        self.ttl_schedule = ttl_schedule
        self.stale_pending_threshold_seconds = stale_pending_threshold_seconds
        self.ch_start_grace_period_seconds = ch_start_grace_period_seconds

    def execute(
        self,
        team: Team,
        query_info: QueryInfo,
        start: datetime,
        end: datetime,
        run_insert: Callable[[Team, PreaggregationJob], None] | None = None,
    ) -> PreaggregationResult:
        """
        Execute preaggregation jobs for the given query and time range.

        Runs a loop that inserts missing ranges first (doing useful work), then
        waits for any pending jobs created by other executors. The loop repeats
        until all ranges are covered or an error/timeout occurs.

        Returns ready=True with job_ids on success, or ready=False on any failure.
        Never returns partial results — either all ranges are covered or none.

        Args:
            run_insert: Optional custom insert function. If not provided, uses the
                        default AST-based run_preaggregation_insert with query_info.
        """
        insert_fn = run_insert or (lambda t, j: run_preaggregation_insert(t, j, query_info))
        query_hash = compute_query_hash(query_info)

        errors: list[str] = []
        failures = 0
        start_time = time.monotonic()
        interval = self.poll_interval_seconds
        subscribed_ids: set[uuid.UUID] = set()
        pubsub: redis_lib.client.PubSub | None = None

        try:
            while True:
                if time.monotonic() - start_time >= self.wait_timeout_seconds:
                    errors.append("Timeout waiting for preaggregation jobs")
                    return PreaggregationResult(ready=False, job_ids=[], errors=errors)

                # Step 1: See what exists, filter out stale READY jobs
                existing_jobs = find_existing_jobs(team, query_hash, start, end)
                fresh_jobs = self._filter_by_freshness(existing_jobs)
                pending_jobs = [j for j in fresh_jobs if j.status == PreaggregationJob.Status.PENDING]

                # Step 2: Find missing ranges, split at TTL boundaries
                missing_ranges = find_missing_contiguous_windows(fresh_jobs, start, end)
                ttl_ranges = split_ranges_by_ttl(missing_ranges, self.ttl_schedule)

                # Step 3: Insert missing ranges
                did_work = False
                if ttl_ranges and failures <= self.max_retries:
                    for range_start, range_end, ttl in ttl_ranges:
                        try:
                            with transaction.atomic():
                                new_job = create_preaggregation_job(team, query_hash, range_start, range_end, ttl)
                        except IntegrityError:
                            # Another executor created a PENDING job for this range — loop will pick it up
                            did_work = True
                            continue

                        try:
                            insert_fn(team, new_job)
                            new_job.status = PreaggregationJob.Status.READY
                            new_job.computed_at = django_timezone.now()
                            new_job.save()
                            publish_job_completion(new_job.id, "ready")
                        except Exception as e:
                            new_job.status = PreaggregationJob.Status.FAILED
                            new_job.error = str(e)
                            new_job.save()
                            publish_job_completion(new_job.id, "failed")
                            if is_non_retryable_error(e):
                                errors.append(str(e))
                                return PreaggregationResult(ready=False, job_ids=[], errors=errors)
                            failures += 1
                            if failures > self.max_retries:
                                errors.append(f"Max retries ({self.max_retries}) exceeded: {e}")
                                return PreaggregationResult(ready=False, job_ids=[], errors=errors)
                        did_work = True

                if ttl_ranges and failures > self.max_retries:
                    errors.append("Max retries exceeded for preaggregation")
                    return PreaggregationResult(ready=False, job_ids=[], errors=errors)

                if did_work:
                    interval = self.poll_interval_seconds
                    continue

                # Step 4: Wait for pending jobs
                if pending_jobs:
                    if pubsub is None:
                        pubsub = subscribe_to_jobs([j.id for j in pending_jobs])
                        subscribed_ids = {j.id for j in pending_jobs}
                    else:
                        for job in pending_jobs:
                            if job.id not in subscribed_ids:
                                pubsub.subscribe(job_channel(job.id))
                                subscribed_ids.add(job.id)

                    for job in pending_jobs:
                        if self._is_job_stale(job):
                            self._try_mark_stale_job_as_failed(job)

                    remaining = self.wait_timeout_seconds - (time.monotonic() - start_time)
                    wait_time = min(interval, remaining)
                    if wait_time > 0:
                        self._wait_for_notification(pubsub, wait_time)
                    interval = min(interval * 2, self.max_poll_interval_seconds)
                    continue

                # Step 5: Nothing to insert, nothing pending — done
                break
        finally:
            if pubsub:
                try:
                    pubsub.unsubscribe()
                    pubsub.close()
                except Exception:
                    pass

        # All ranges covered — collect READY job IDs
        final_jobs = find_existing_jobs(team, query_hash, start, end)
        final_fresh = self._filter_by_freshness(final_jobs)
        final_ready = filter_overlapping_jobs([j for j in final_fresh if j.status == PreaggregationJob.Status.READY])
        return PreaggregationResult(ready=True, job_ids=[j.id for j in final_ready])

    def _try_mark_stale_job_as_failed(self, job: PreaggregationJob) -> bool:
        """
        Try to mark a stale PENDING job as FAILED.

        Uses atomic update with status check to prevent races.
        Returns True if this call marked it, False if another waiter did or status changed.
        """
        updated = PreaggregationJob.objects.filter(
            id=job.id,
            status=PreaggregationJob.Status.PENDING,  # Only if still PENDING
        ).update(
            status=PreaggregationJob.Status.FAILED,
            error="Job was stale (executor may have crashed)",
        )
        if updated > 0:
            publish_job_completion(job.id, "failed")
        return updated > 0

    def _is_job_stale(self, job: PreaggregationJob) -> bool:
        """Check if a PENDING job is stale using Redis-based CH liveness.

        Uses only Redis checks (no PG queries):
        - If CH heartbeat is alive: never stale (query is running)
        - If CH INSERT never started: stale after ch_start_grace_period_seconds
        - If CH INSERT started but heartbeat expired: stale after stale_pending_threshold_seconds
        """
        if is_ch_query_alive(job.team_id, job.id):
            return False

        if not has_ch_query_started(job.id):
            job_age = (django_timezone.now() - job.created_at).total_seconds()
            return job_age > self.ch_start_grace_period_seconds

        job_age = (django_timezone.now() - job.created_at).total_seconds()
        return job_age > self.stale_pending_threshold_seconds

    def _filter_by_freshness(self, jobs: list[PreaggregationJob]) -> list[PreaggregationJob]:
        """Filter jobs by freshness according to the TTL schedule.

        PENDING jobs always pass (they were recently created and we should wait).
        READY jobs must satisfy: created_at + desired_ttl >= now().

        This is per-query: a job created by executor A with a long TTL may be
        rejected by executor B using a stricter schedule for the same hash.
        """
        now = django_timezone.now()
        result = []
        for job in jobs:
            if job.status == PreaggregationJob.Status.PENDING:
                result.append(job)
            else:
                desired_ttl = self.ttl_schedule.get_ttl(job.time_range_start)
                if job.created_at + timedelta(seconds=desired_ttl) >= now:
                    result.append(job)
        return result

    def _wait_for_notification(self, pubsub: redis_lib.client.PubSub, timeout: float) -> dict | None:
        """Block until a pubsub message arrives or timeout. Extracted for testability."""
        return pubsub.get_message(timeout=timeout)


def ensure_preaggregated(
    team: Team,
    insert_query: str,
    time_range_start: datetime,
    time_range_end: datetime,
    ttl_seconds: int | dict[str, int] = DEFAULT_TTL_SECONDS,
    table: PreaggregationTable = PreaggregationTable.PREAGGREGATION_RESULTS,
    placeholders: dict[str, ast.Expr] | None = None,
) -> PreaggregationResult:
    """
    Ensure preaggregated data exists for the given query and time range.

    This is the manual API for preaggregation. Unlike the automatic transformation,
    the caller provides the INSERT SELECT query directly. The query should produce
    columns matching the target table schema.

    The following columns are added automatically:
    - team_id: Added as the first column
    - job_id: Added as the second column
    - expires_at: Added as the last column (derived from ttl_seconds + safety buffer)

    The following placeholders are added automatically per-job:
    - {time_window_min}: Start of the job's time window (datetime)
    - {time_window_max}: End of the job's time window (datetime)

    Your query MUST use these placeholders to filter data to the correct time range.

    Args:
        team: The team to create preaggregation for
        insert_query: A SELECT query string with placeholders. Use {time_window_min}
                      and {time_window_max} for time filtering.
        time_range_start: Start of the overall time range (inclusive)
        time_range_end: End of the overall time range (exclusive)
        ttl_seconds: How long before the data expires. Either:
                     - int: uniform TTL in seconds for all ranges (default 7 days)
                     - dict: maps date strings to TTL values. Keys are parsed using
                       relative_date_parse (e.g. "7d", "24h", "2026-02-15"). The
                       "default" key sets the fallback TTL. Uses team timezone.
        table: The target preaggregation table (default "preaggregation_results")
        placeholders: Additional placeholder values to substitute into the query.
                      time_window_min and time_window_max are added automatically.

    Returns:
        PreaggregationResult with job_ids that can be used to query the data

    Example:
        result = ensure_preaggregated(
            team=team,
            insert_query=\"\"\"
                SELECT
                    toStartOfDay(timestamp) as time_window_start,
                    [] as breakdown_value,
                    uniqExactState(person_id) as uniq_exact_state
                FROM events
                WHERE event = '$pageview'
                    AND timestamp >= {time_window_min}
                    AND timestamp < {time_window_max}
                GROUP BY time_window_start
            \"\"\",
            time_range_start=datetime(2024, 1, 1),
            time_range_end=datetime(2024, 1, 8),
            ttl_seconds={
                "0d": 15 * 60,           # current day: 15 min
                "1d": 60 * 60,            # previous day: 1 hour
                "7d": 24 * 60 * 60,       # last week: 1 day
                "default": 7 * 24 * 60 * 60,  # older: 7 days
            },
        )
        # Use result.job_ids to query from preaggregation_results
    """
    base_placeholders = placeholders or {}
    _validate_no_reserved_placeholders(base_placeholders)

    # Parse the query template with sentinel time placeholders for stable hashing
    hash_placeholders = {
        **base_placeholders,
        "time_window_min": ast.Constant(value="__TIME_WINDOW_MIN__"),
        "time_window_max": ast.Constant(value="__TIME_WINDOW_MAX__"),
    }
    parsed_for_hash = parse_select(insert_query, placeholders=hash_placeholders)
    assert isinstance(parsed_for_hash, ast.SelectQuery)

    query_info = QueryInfo(
        query=parsed_for_hash,
        table=table,
        timezone=team.timezone,
    )

    def _run_manual_insert(t: Team, job: PreaggregationJob) -> None:
        insert_sql, values = _build_manual_insert_sql(
            team=t,
            job=job,
            insert_query=insert_query,
            table=table,
            base_placeholders=base_placeholders,
        )
        set_ch_query_started(job.id)
        with tags_context(client_query_id=str(job.id), team_id=t.id):
            sync_execute(
                insert_sql,
                values,
                settings={
                    "max_execution_time": HOGQL_INCREASED_MAX_EXECUTION_TIME,
                    **HogQLQuerySettings(load_balancing="in_order").model_dump(exclude_none=True),
                },
            )

    ttl_schedule = parse_ttl_schedule(ttl_seconds, team.timezone)
    executor = PreaggregationExecutor(ttl_schedule=ttl_schedule)
    return executor.execute(team, query_info, time_range_start, time_range_end, run_insert=_run_manual_insert)


def _build_manual_insert_sql(
    team: Team,
    job: PreaggregationJob,
    insert_query: str,
    table: PreaggregationTable,
    base_placeholders: dict[str, ast.Expr] | None = None,
) -> tuple[str, dict]:
    """
    Build INSERT SQL for manual preaggregation.

    Parses the query string with time placeholders for the job's time range,
    then adds team_id, job_id, and expires_at to the SELECT list.

    The query should use {time_window_min} and {time_window_max} placeholders
    for time filtering - these are substituted with the job's time range.
    """
    if base_placeholders:
        _validate_no_reserved_placeholders(base_placeholders)

    # Build placeholders with job-specific time values
    all_placeholders = {
        **(base_placeholders or {}),
        "time_window_min": ast.Constant(value=job.time_range_start),
        "time_window_max": ast.Constant(value=job.time_range_end),
    }

    # Parse the query with all placeholders — returns a fresh AST we can mutate
    query = parse_select(insert_query, placeholders=all_placeholders)
    assert isinstance(query, ast.SelectQuery)
    assert query.select is not None, "SelectQuery must have select expressions"

    # Add team_id as the first column
    team_id_expr = ast.Alias(alias="team_id", expr=ast.Constant(value=team.id))
    query.select.insert(0, team_id_expr)

    # Add job_id as the second column (after team_id)
    job_id_expr = ast.Alias(
        alias="job_id",
        expr=ast.Call(name="toUUID", args=[ast.Constant(value=str(job.id))]),
    )
    query.select.insert(1, job_id_expr)

    ch_expires_at = _get_ch_expires_at(job, table)
    expires_at_expr = ast.Alias(alias="expires_at", expr=ast.Constant(value=ch_expires_at))
    query.select.append(expires_at_expr)

    # Print to SQL
    context = HogQLContext(team_id=team.id, team=team, enable_select_queries=True, limit_top_select=False)
    select_sql, _ = prepare_and_print_ast(
        query,
        context=context,
        dialect="clickhouse",
    )

    # Build column list from the query's SELECT expressions
    columns = []
    for expr in query.select:
        if isinstance(expr, ast.Alias):
            columns.append(expr.alias)
        else:
            # For non-aliased expressions, we need to infer the column name
            # This shouldn't happen in well-formed queries
            raise ValueError(f"All SELECT expressions must be aliased: {expr}")

    column_list = ", ".join(columns)
    sql = f"INSERT INTO {table} ({column_list})\n{select_sql}"

    return sql, context.values
