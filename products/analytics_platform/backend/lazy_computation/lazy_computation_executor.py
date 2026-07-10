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
import structlog
from clickhouse_driver.errors import ServerException
from prometheus_client import Counter

from posthog.hogql import ast
from posthog.hogql.constants import (
    MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
    HogQLQuerySettings,
    get_default_hogql_global_settings,
)
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE
from posthog.clickhouse.query_tagging import tags_context
from posthog.models.team import Team
from posthog.settings import DEBUG, HOGQL_INCREASED_MAX_EXECUTION_TIME, TEST
from posthog.utils import relative_date_parse_with_delta_mapping

from products.analytics_platform.backend.lazy_computation.computation_notifications import (
    has_ch_query_started,
    is_ch_query_alive,
    job_channel,
    publish_job_completion,
    set_ch_query_started,
    subscribe_to_jobs,
)
from products.analytics_platform.backend.models import PreaggregationJob

logger = structlog.get_logger(__name__)

# Default TTL for lazy computed data (how long before ClickHouse deletes it)
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# ClickHouse data outlives the PG job by this amount. This prevents races where we fetch a job in PG, use it, but while
# waiting for something else, it expires and is deleted in clickhouse.
EXPIRY_BUFFER_SECONDS = 48 * 60 * 60  # 48 hours

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

# Quorum for INSERT queries: both aux replicas must acknowledge writes before the INSERT
# returns. This ensures data is replicated before the subsequent SELECT reads it,
# preventing stale reads from hitting a replica that hasn't received the data yet
# (Approach E in CONSISTENCY.md, paired with in_order load balancing on reads).
# An explicit 2 rather than "auto": auto means majority of *registered* replicas, which
# counts dead ZooKeeper registrations — during a node replacement that left the old
# replicas registered (2 live of 4 registered), auto demanded an unreachable 3 acks and
# every insert hung for the full quorum timeout. 2 equals the majority whenever
# registrations are correct (aux runs 2 replicas; it stays a majority at 3) and is
# immune to ghost registrations inflating the denominator.
# Disabled in tests AND local dev (DEBUG) — both run against a single-node ClickHouse
# where a quorum insert waits for an acknowledgement that never comes (the local
# replica writes immediately but ClickHouse still blocks on the quorum protocol).
PREAGGREGATION_INSERT_QUORUM: str | int = 0 if TEST or DEBUG else 2


# Mirrors the `lazy_computation.executed` structured log so the same outcomes
# (`success` / `timeout` / `non_retryable_error` / `max_retries_exceeded`) are
# countable in Prometheus without log-based aggregation.
#
# `cache_state` values:
#   - `hit`         → the request did no new work (no jobs created, no waits).
#   - `partial_hit` → the request had to do work but found pre-existing READY data.
#   - `miss`        → the request had to do work and found no pre-existing data.
#
# See README.md § Observability for example PromQL queries.
LAZY_COMPUTATION_EXECUTIONS_TOTAL = Counter(
    "lazy_computation_executions_total",
    "Lazy computation executor invocations, labeled by outcome / cache_state / table.",
    ["outcome", "cache_state", "table"],
)


# Per-job lifecycle counters. The executor framework processes jobs synchronously
# inside `execute()` — there is no background queue and PENDING is just "an INSERT
# is currently running in some pod". A point-in-time sample of PENDING rows can't
# answer "are we keeping up?" because finished jobs vanish from the live set as
# fast as new ones arrive. These counters are the queue-throughput primitive
# instead: subtract the rates to get net backlog growth, slice by `outcome` to
# see whether failures or staleness are climbing.
#
# `created.cache_state` mirrors the executor-level `lazy_computation_executions_total`
# label so a per-job rate can be attributed to the kind of execute() call that
# spawned it. Hits don't create anything, so only `miss` and `partial_hit` appear:
#   - `miss`        → execute() found no pre-existing READY data; every job in
#                     this counter slice is part of a fresh population.
#   - `partial_hit` → execute() found some pre-existing READY data; jobs here are
#                     top-ups filling the gaps.
# Use `rate(created{cache_state="miss"}) / rate(executions_total{cache_state="miss"})`
# to get average jobs per miss execution (i.e. average miss window size).
#
# `finished` outcomes:
#   - `ready`  → INSERT succeeded, row moved PENDING → READY.
#   - `failed` → INSERT raised (retryable or non-retryable), row moved PENDING → FAILED.
#   - `stale`  → another waiter detected the owning executor crashed and marked
#                the row FAILED via `_try_mark_stale_job_as_failed`.
LAZY_COMPUTATION_JOBS_CREATED_TOTAL = Counter(
    "lazy_computation_jobs_created_total",
    "PreaggregationJob rows inserted in PENDING status (one per missing range, per executor).",
    ["cache_state", "table"],
)
LAZY_COMPUTATION_JOBS_FINISHED_TOTAL = Counter(
    "lazy_computation_jobs_finished_total",
    "PreaggregationJob rows that reached a terminal status, labeled by outcome and table.",
    ["outcome", "table"],
)


def _get_insert_settings(team_id: int, *, spill_to_disk: bool = False) -> dict:
    """Build ClickHouse settings for preaggregation INSERT queries.

    Starts from the same HogQLGlobalSettings defaults that execute_hogql_query
    uses for regular queries, then applies INSERT-specific overrides.

    `spill_to_disk` is opt-in per precompute kind: it only helps inserts whose
    GROUP BY hash table can grow large (high-cardinality breakdowns), and most
    kinds never approach the threshold, so callers enable it deliberately rather
    than paying for it everywhere.
    """
    settings = get_default_hogql_global_settings(team_id=team_id).model_dump(exclude_none=True)
    settings.pop("readonly", None)  # INSERTs need write access
    settings.update(
        {
            "max_execution_time": HOGQL_INCREASED_MAX_EXECUTION_TIME,
            "insert_quorum": PREAGGREGATION_INSERT_QUORUM,
            # The executor marks a job READY as soon as the INSERT returns, so rows must be on the
            # shards by then — not sitting in the initiator's async distribution queue, where they
            # become visible to readers only minutes later. We set this per-insert rather than
            # relying on the cluster's global default, which is not guaranteed to be synchronous.
            # Uses the legacy name of `distributed_foreground_insert` (renamed in ClickHouse 23.x)
            # for version compatibility.
            "insert_distributed_sync": 1,
            **HogQLQuerySettings(load_balancing="in_order").model_dump(exclude_none=True),
        }
    )
    if spill_to_disk:
        # Spill heavy GROUP BYs to disk instead of OOMing. This is a spill
        # *threshold*, not a memory reservation — it lowers peak RAM (vs. holding
        # the whole hash table in memory), so it never over-commits the cluster.
        # High-traffic teams' breakdown inserts (e.g. frustration metrics) otherwise
        # build hash tables past the cluster memory limit and fail with
        # MEMORY_LIMIT_EXCEEDED.
        settings["max_bytes_before_external_group_by"] = MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY
    return settings


@dataclass
class TtlSchedule:
    """Maps time windows to TTL values based on their recency.

    Rules are (cutoff_datetime, ttl_seconds) pairs sorted by cutoff descending.
    A window matches the first rule where window_start >= cutoff. If no rule
    matches, default_ttl_seconds is used.

    `max_window_days` optionally caps how wide `split_ranges_by_ttl` will merge a
    single job, independent of TTL boundaries — so a caller bounds a high-cardinality
    team's GROUP BY by handing in a schedule with a tight cap, regardless of how old
    the requested window is. `None` leaves it uncapped.

    `settling_period_seconds` marks how long after `time_range_end` a window's data can
    still change (e.g. the 24h session pad in web analytics: sessions opened in the
    window keep evolving until they close). A job *computed before* the window settled
    (`time_range_end + settling_period`) captured in-motion data, so its freshness is
    capped at the settling moment regardless of the band TTL — it recomputes right when
    the data is complete instead of freezing an in-motion snapshot for a long band TTL.
    Jobs computed after the window settled keep the full band TTL. This matters for
    non-UTC teams, whose UTC-aligned edge windows can land in a long-TTL band while
    still settling. `None` disables the check.

    Use parse_ttl_schedule() to create from user-facing dict format.
    """

    rules: list[tuple[datetime, int]]
    default_ttl_seconds: int
    max_window_days: int | None = None
    settling_period_seconds: int | None = None

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
    max_window_days: int | None = None,
    settling_period_seconds: int | None = None,
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

    `max_window_days` is carried onto the resulting schedule to cap job width.

    Raises ValueError for unrecognized keys or non-positive TTL values.
    """
    if isinstance(ttl, int):
        if ttl <= 0:
            raise ValueError(f"TTL must be positive, got {ttl}")
        return TtlSchedule(
            rules=[],
            default_ttl_seconds=ttl,
            max_window_days=max_window_days,
            settling_period_seconds=settling_period_seconds,
        )

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
    return TtlSchedule(
        rules=rules,
        default_ttl_seconds=default_ttl,
        max_window_days=max_window_days,
        settling_period_seconds=settling_period_seconds,
    )


def split_ranges_by_ttl(
    ranges: list[tuple[datetime, datetime]],
    schedule: TtlSchedule,
) -> list[tuple[datetime, datetime, int]]:
    """Split time ranges at TTL boundaries.

    Re-expands each range into daily windows, assigns a TTL per window, and
    merges consecutive windows with the same TTL. This prevents a single job
    from covering days with different TTL requirements.

    `schedule.max_window_days` additionally caps the merged job width: a merge
    also breaks when adding the next day would exceed it. This bounds a job's
    GROUP BY (independent of TTL and of how old the window is) so its hash table
    stays under the memory limit.
    """
    max_window_days = schedule.max_window_days
    result: list[tuple[datetime, datetime, int]] = []

    for range_start, range_end in ranges:
        windows = get_daily_windows(range_start, range_end)
        if not windows:
            continue

        current_start, current_end = windows[0]
        current_ttl = schedule.get_ttl(current_start)

        for window_start, window_end in windows[1:]:
            ttl = schedule.get_ttl(window_start)
            exceeds_cap = max_window_days is not None and (window_end - current_start) > timedelta(days=max_window_days)
            if ttl == current_ttl and not exceeds_cap:
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
    # The rows/bytes-to-read cap is deterministic for a given window: the data
    # won't shrink between attempts, so an immediate retry re-scans the same
    # terabytes only to fail the same way. Fail fast so the caller can fall
    # back or narrow the window.
    307,  # TOO_MANY_ROWS_OR_BYTES
    # An OOM won't succeed on an immediate retry with the same window — retrying just
    # adds memory pressure to a cluster that already signaled it's out of memory. Fail
    # fast so the caller can react (e.g. cap the team's window) and fall back.
    241,  # MEMORY_LIMIT_EXCEEDED
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


# ClickHouse MEMORY_LIMIT_EXCEEDED. Surfaced on the result so callers can react to an OOM
# (e.g. cap a high-cardinality team's future inserts) instead of parsing error text.
MEMORY_LIMIT_EXCEEDED_CODE = 241


def is_memory_limit_error(error: Exception) -> bool:
    """True if the error (or any wrapped cause) is a ClickHouse MEMORY_LIMIT_EXCEEDED."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ServerException) and current.code == MEMORY_LIMIT_EXCEEDED_CODE:
            return True
        current = current.__cause__
    return False


class LazyComputationTable(StrEnum):
    """Allowed target tables for lazy-computed results."""

    PREAGGREGATION_RESULTS = "preaggregation_results"
    EXPERIMENT_EXPOSURES_PREAGGREGATED = "experiment_exposures_preaggregated"
    EXPERIMENT_METRIC_EVENTS_PREAGGREGATED = "experiment_metric_events_preaggregated"
    MARKETING_TOUCHPOINTS_PREAGGREGATED = "marketing_touchpoints_preaggregated"
    MARKETING_CONVERSIONS_PREAGGREGATED = "marketing_conversions_preaggregated"
    MARKETING_COSTS_PREAGGREGATED = "marketing_costs_preaggregated"
    WEB_OVERVIEW_PREAGGREGATED = "web_overview_preaggregated"
    WEB_STATS_PREAGGREGATED = "web_stats_preaggregated"
    WEB_STATS_PATHS_PREAGGREGATED = "web_stats_paths_preaggregated"
    WEB_VITALS_PATHS_PREAGGREGATED = "web_vitals_paths_preaggregated"
    WEB_STATS_FRUSTRATION_PREAGGREGATED = "web_stats_frustration_preaggregated"
    WEB_GOALS_PREAGGREGATED = "web_goals_preaggregated"
    # Fixed-dimension tables driven by the scheduled web_dimensional_precompute
    # Dagster job (the precomputation-framework successor to v2 pre-aggregation).
    WEB_STATS_DIMENSIONAL_PREAGGREGATED = "web_stats_dimensional_preaggregated"
    WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED = "web_bounces_dimensional_preaggregated"


# Tables where expires_at is a Date (not DateTime64). Date truncates to midnight,
# so an expires_at just after midnight would round down to a time *before* the PG
# job expires. We add an extra day of buffer for these tables.
_DATE_EXPIRES_AT_TABLES: set[LazyComputationTable] = {
    LazyComputationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
    LazyComputationTable.EXPERIMENT_METRIC_EVENTS_PREAGGREGATED,
    LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED,
    LazyComputationTable.MARKETING_CONVERSIONS_PREAGGREGATED,
    LazyComputationTable.MARKETING_COSTS_PREAGGREGATED,
}


def _get_ch_expires_at(job: "PreaggregationJob", table: LazyComputationTable) -> datetime:
    """Compute the ClickHouse expires_at for a job, accounting for the table's column type."""
    assert job.expires_at is not None
    extra_days = 1 if table in _DATE_EXPIRES_AT_TABLES else 0
    return job.expires_at + timedelta(seconds=EXPIRY_BUFFER_SECONDS, days=extra_days)


@dataclass
class QueryInfo:
    """Normalized query information for lazy computation matching."""

    query: ast.SelectQuery
    table: LazyComputationTable
    timezone: str = "UTC"
    breakdown_fields: list[str] = field(default_factory=list)


@dataclass
class LazyComputationResult:
    """Result of executing lazy computation jobs."""

    ready: bool
    job_ids: list[uuid.UUID]
    errors: list[str] = field(default_factory=list)
    # True if any insert failed with ClickHouse MEMORY_LIMIT_EXCEEDED. Lets callers react
    # to an OOM (e.g. cap a high-cardinality team's future inserts) without parsing errors.
    memory_exceeded: bool = False
    # True when the returned job_ids include recently-expired jobs served under the
    # executor's serve-stale grace instead of recomputing inline. The data is complete
    # but up to (TTL + grace) old; the caller decides whether to surface that.
    stale: bool = False


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
    expired_grace_seconds: float = 0,
) -> list[PreaggregationJob]:
    """
    Find all existing lazy computation jobs for the given team and query hash
    that overlap with the requested time range.

    Excludes expired jobs. ClickHouse data outlives the PG job by
    EXPIRY_BUFFER_SECONDS, so queries in flight when a job expires still
    find data. `expired_grace_seconds` relaxes the expiry cutoff to also return
    recently-expired jobs (for serve-stale reads); it must stay well under
    EXPIRY_BUFFER_SECONDS or the PG row may outlive its ClickHouse data.
    """
    min_expires_at = django_timezone.now() - timedelta(seconds=expired_grace_seconds)

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


def create_lazy_computation_job(
    team: Team,
    query_hash: str,
    time_range_start: datetime,
    time_range_end: datetime,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> PreaggregationJob:
    """Create a new computation job in PENDING status with expiry time."""
    expires_at = django_timezone.now() + timedelta(seconds=ttl_seconds)
    return PreaggregationJob.objects.create(
        team=team,
        query_hash=query_hash,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        status=PreaggregationJob.Status.PENDING,
        expires_at=expires_at,
    )


def build_lazy_computation_insert_sql(
    team: Team,
    job_id: str,
    select_query: ast.SelectQuery,
    time_range_start: datetime,
    time_range_end: datetime,
    expires_at: datetime,
) -> tuple[str, dict]:
    """
    Build the INSERT ... SELECT SQL for populating lazy-computed results.

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


def run_lazy_computation_insert(
    team: Team,
    job: PreaggregationJob,
    query_info: QueryInfo,
) -> None:
    """Run the INSERT query to populate lazy-computed results in ClickHouse."""
    ch_expires_at = _get_ch_expires_at(job, LazyComputationTable.PREAGGREGATION_RESULTS)

    insert_sql, values = build_lazy_computation_insert_sql(
        team=team,
        job_id=str(job.id),
        select_query=query_info.query,
        time_range_start=job.time_range_start,
        time_range_end=job.time_range_end,
        expires_at=ch_expires_at,
    )

    set_ch_query_started(job.id)
    with tags_context(
        client_query_id=str(job.id),
        team_id=team.id,
        precompute_window_start=str(job.time_range_start),
        precompute_window_end=str(job.time_range_end),
    ):
        sync_execute(
            insert_sql,
            values,
            settings=_get_insert_settings(team.id),
        )


class LazyComputationExecutor:
    """
    Executes computation jobs with configurable waiting behavior.

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
    - ttl_schedule: TtlSchedule controlling how long lazy-computed data persists per time range
    - stale_pending_threshold_seconds: How long before a PENDING job is considered stale
    - ch_start_grace_period_seconds: Grace period before declaring "not started" as stale
    - serve_stale_grace_seconds: When set, a request that would otherwise compute inline
      (or block on another executor's pending jobs) is served from READY jobs that expired
      within the last N seconds — complete-but-stale data, returned immediately with
      `stale=True`. Must stay well under EXPIRY_BUFFER_SECONDS (48h) so the underlying
      ClickHouse rows are guaranteed to still exist.
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
        serve_stale_grace_seconds: float | None = None,
    ) -> None:
        if serve_stale_grace_seconds is not None and serve_stale_grace_seconds >= EXPIRY_BUFFER_SECONDS:
            raise ValueError("serve_stale_grace_seconds must be below EXPIRY_BUFFER_SECONDS")
        self.wait_timeout_seconds = wait_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_poll_interval_seconds = max_poll_interval_seconds
        self.max_retries = max_retries
        self.ttl_schedule = ttl_schedule
        self.stale_pending_threshold_seconds = stale_pending_threshold_seconds
        self.ch_start_grace_period_seconds = ch_start_grace_period_seconds
        self.serve_stale_grace_seconds = serve_stale_grace_seconds

    def execute(
        self,
        team: Team,
        query_info: QueryInfo,
        start: datetime,
        end: datetime,
        run_insert: Callable[[Team, PreaggregationJob], None] | None = None,
    ) -> LazyComputationResult:
        """
        Execute computation jobs for the given query and time range.

        Runs a loop that inserts missing ranges first (doing useful work), then
        waits for any pending jobs created by other executors. The loop repeats
        until all ranges are covered or an error/timeout occurs.

        Returns ready=True with job_ids on success, or ready=False on any failure.
        Never returns partial results — either all ranges are covered or none.

        Args:
            run_insert: Optional custom insert function. If not provided, uses the
                        default AST-based run_computation_insert with query_info.
        """
        insert_fn = run_insert or (lambda t, j: run_lazy_computation_insert(t, j, query_info))
        query_hash = compute_query_hash(query_info)

        errors: list[str] = []
        failures = 0
        memory_exceeded = False
        start_time = time.monotonic()
        interval = self.poll_interval_seconds
        subscribed_ids: set[uuid.UUID] = set()
        pubsub: redis_lib.client.PubSub | None = None
        jobs_created = 0
        waited_job_ids: set[uuid.UUID] = set()

        had_ready_at_start: bool | None = None

        def _log_execution(outcome: str, result: LazyComputationResult) -> None:
            if jobs_created == 0 and not waited_job_ids:
                cache_state = "hit"
            elif had_ready_at_start:
                cache_state = "partial_hit"
            else:
                cache_state = "miss"
            LAZY_COMPUTATION_EXECUTIONS_TOTAL.labels(
                outcome=outcome,
                cache_state=cache_state,
                table=str(query_info.table),
            ).inc()
            logger.info(
                "lazy_computation.executed",
                query_hash=query_hash,
                table=str(query_info.table),
                outcome=outcome,
                cache_state=cache_state,
                total_duration_ms=round((time.monotonic() - start_time) * 1000),
                jobs_created=jobs_created,
                jobs_waited_for=len(waited_job_ids),
                time_range_start=str(start),
                time_range_end=str(end),
                time_range_days=(end - start).days,
            )

        try:
            while True:
                if time.monotonic() - start_time >= self.wait_timeout_seconds:
                    errors.append("Timeout waiting for computation jobs")
                    result = LazyComputationResult(
                        ready=False, job_ids=[], errors=errors, memory_exceeded=memory_exceeded
                    )
                    _log_execution("timeout", result)
                    return result

                # Step 1: See what exists, filter out stale READY jobs
                existing_jobs = find_existing_jobs(team, query_hash, start, end)
                fresh_jobs = self._filter_by_freshness(existing_jobs)
                pending_jobs = [j for j in fresh_jobs if j.status == PreaggregationJob.Status.PENDING]

                # Step 2: Find missing ranges, split at TTL boundaries
                missing_ranges = find_missing_contiguous_windows(fresh_jobs, start, end)
                ttl_ranges = split_ranges_by_ttl(missing_ranges, self.ttl_schedule)

                if had_ready_at_start is None:
                    had_ready_at_start = any(j.status == PreaggregationJob.Status.READY for j in fresh_jobs)

                # Step 2.5: Serve stale. If this request would otherwise compute inline or
                # block on another executor's pending jobs, and READY jobs within the grace
                # fully cover the range, return them immediately — complete-but-stale beats
                # blocking. Whoever refreshes (the warmer, or a request after the grace)
                # replaces the data; `filter_overlapping_jobs` always prefers newer jobs.
                if self.serve_stale_grace_seconds is not None and (ttl_ranges or pending_jobs):
                    graced = find_existing_jobs(
                        team, query_hash, start, end, expired_grace_seconds=self.serve_stale_grace_seconds
                    )
                    graced_ready = self._filter_by_freshness(
                        [j for j in graced if j.status == PreaggregationJob.Status.READY],
                        grace_seconds=self.serve_stale_grace_seconds,
                    )
                    # Coverage must be checked on the overlap-filtered set that will actually
                    # be returned: the filter prefers newer jobs, so a newer narrow job can
                    # evict an older broad one and reopen a gap the unfiltered set covered.
                    covering = filter_overlapping_jobs(graced_ready)
                    if not find_missing_contiguous_windows(covering, start, end):
                        result = LazyComputationResult(
                            ready=True,
                            job_ids=[j.id for j in covering],
                            stale=True,
                        )
                        _log_execution("stale_hit", result)
                        return result

                # Step 3: Insert missing ranges
                did_work = False
                if ttl_ranges and failures <= self.max_retries:
                    for range_start, range_end, ttl in ttl_ranges:
                        # Each insert runs inline and is bounded only by the ClickHouse
                        # max_execution_time, which is larger than our wait budget. A capped
                        # (narrow) window can produce many ranges; stop before starting another
                        # insert once the budget is spent rather than running the whole set
                        # back-to-back and blowing well past wait_timeout_seconds.
                        if time.monotonic() - start_time >= self.wait_timeout_seconds:
                            errors.append("Timeout waiting for computation jobs")
                            result = LazyComputationResult(
                                ready=False, job_ids=[], errors=errors, memory_exceeded=memory_exceeded
                            )
                            _log_execution("timeout", result)
                            return result

                        try:
                            with transaction.atomic():
                                new_job = create_lazy_computation_job(team, query_hash, range_start, range_end, ttl)
                        except IntegrityError:
                            # Another executor created a PENDING job for this range — loop will pick it up
                            did_work = True
                            continue

                        # `had_ready_at_start` is set above before the create loop runs and
                        # is the same signal `_log_execution` uses to compute the executor's
                        # final cache_state. Reusing it here keeps job-level and
                        # execution-level series aligned. Hits never enter this branch.
                        LAZY_COMPUTATION_JOBS_CREATED_TOTAL.labels(
                            cache_state="partial_hit" if had_ready_at_start else "miss",
                            table=str(query_info.table),
                        ).inc()

                        try:
                            insert_start = time.monotonic()
                            insert_fn(team, new_job)
                            insert_elapsed = time.monotonic() - insert_start
                            new_job.status = PreaggregationJob.Status.READY
                            new_job.computed_at = django_timezone.now()
                            new_job.save()
                            publish_job_completion(new_job.id, "ready")
                            LAZY_COMPUTATION_JOBS_FINISHED_TOTAL.labels(
                                outcome="ready", table=str(query_info.table)
                            ).inc()
                            jobs_created += 1
                            logger.info(
                                "lazy_computation.job_completed",
                                job_id=str(new_job.id),
                                query_hash=query_hash,
                                table=str(query_info.table),
                                time_range_start=str(range_start),
                                time_range_end=str(range_end),
                                ttl_seconds=ttl,
                                insert_duration_ms=round(insert_elapsed * 1000),
                            )
                        except Exception as e:
                            insert_elapsed = time.monotonic() - insert_start
                            memory_exceeded = memory_exceeded or is_memory_limit_error(e)
                            new_job.status = PreaggregationJob.Status.FAILED
                            new_job.error = str(e)
                            new_job.save()
                            publish_job_completion(new_job.id, "failed")
                            LAZY_COMPUTATION_JOBS_FINISHED_TOTAL.labels(
                                outcome="failed", table=str(query_info.table)
                            ).inc()
                            jobs_created += 1
                            logger.warning(
                                "lazy_computation.job_failed",
                                job_id=str(new_job.id),
                                query_hash=query_hash,
                                table=str(query_info.table),
                                time_range_start=str(range_start),
                                time_range_end=str(range_end),
                                ttl_seconds=ttl,
                                insert_duration_ms=round(insert_elapsed * 1000),
                                error=str(e)[:500],
                                error_type=type(e).__name__,
                                is_retryable=not is_non_retryable_error(e),
                                failure_number=failures + 1,
                            )
                            if is_non_retryable_error(e):
                                errors.append(str(e))
                                result = LazyComputationResult(
                                    ready=False, job_ids=[], errors=errors, memory_exceeded=memory_exceeded
                                )
                                _log_execution("non_retryable_error", result)
                                return result
                            failures += 1
                            if failures > self.max_retries:
                                errors.append(f"Max retries ({self.max_retries}) exceeded: {e}")
                                result = LazyComputationResult(
                                    ready=False, job_ids=[], errors=errors, memory_exceeded=memory_exceeded
                                )
                                _log_execution("max_retries_exceeded", result)
                                return result
                        did_work = True

                if ttl_ranges and failures > self.max_retries:
                    errors.append("Max retries exceeded for computation")
                    result = LazyComputationResult(
                        ready=False, job_ids=[], errors=errors, memory_exceeded=memory_exceeded
                    )
                    _log_execution("max_retries_exceeded", result)
                    return result

                if did_work:
                    interval = self.poll_interval_seconds
                    continue

                # Step 4: Wait for pending jobs
                if pending_jobs:
                    waited_job_ids.update(j.id for j in pending_jobs)

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
                            marked = self._try_mark_stale_job_as_failed(job)
                            if marked:
                                LAZY_COMPUTATION_JOBS_FINISHED_TOTAL.labels(
                                    outcome="stale", table=str(query_info.table)
                                ).inc()
                                logger.warning(
                                    "lazy_computation.job_marked_stale",
                                    job_id=str(job.id),
                                    query_hash=query_hash,
                                    table=str(query_info.table),
                                    job_age_seconds=round((django_timezone.now() - job.created_at).total_seconds()),
                                )

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
        result = LazyComputationResult(ready=True, job_ids=[j.id for j in final_ready])
        _log_execution("success", result)
        return result

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

    def _filter_by_freshness(
        self, jobs: list[PreaggregationJob], grace_seconds: float = 0.0
    ) -> list[PreaggregationJob]:
        """Filter jobs by freshness according to the TTL schedule.

        PENDING jobs always pass (they were recently created and we should wait).
        READY jobs must satisfy: created_at + desired_ttl + grace_seconds >= now(), and,
        when the schedule carries a `settling_period_seconds`, a job computed *before* its
        window settled (`created_at < time_range_end + settling_period`) captured
        in-motion data and is only fresh until the settling moment (plus grace): it
        recomputes once the data can no longer change instead of sitting on a long band
        TTL. `grace_seconds` is only non-zero for the serve-stale path and relaxes both
        caps uniformly.

        This is per-query: a job created by executor A with a long TTL may be
        rejected by executor B using a stricter schedule for the same hash.
        """
        now = django_timezone.now()
        settling_period = self.ttl_schedule.settling_period_seconds
        result = []
        for job in jobs:
            if job.status == PreaggregationJob.Status.PENDING:
                result.append(job)
                continue
            desired_ttl = self.ttl_schedule.get_ttl(job.time_range_start)
            fresh_until = job.created_at + timedelta(seconds=desired_ttl + grace_seconds)
            if settling_period is not None:
                settled_at = job.time_range_end + timedelta(seconds=settling_period)
                if job.created_at < settled_at:
                    fresh_until = min(fresh_until, settled_at + timedelta(seconds=grace_seconds))
            if fresh_until >= now:
                result.append(job)
        return result

    def _wait_for_notification(self, pubsub: redis_lib.client.PubSub, timeout: float) -> dict | None:
        """Block until a pubsub message arrives or timeout. Extracted for testability."""
        return pubsub.get_message(timeout=timeout)


def ensure_precomputed(
    team: Team,
    insert_query: str | ast.SelectQuery,
    time_range_start: datetime,
    time_range_end: datetime,
    ttl_seconds: int | dict[str, int] | TtlSchedule = DEFAULT_TTL_SECONDS,
    table: LazyComputationTable = LazyComputationTable.PREAGGREGATION_RESULTS,
    placeholders: dict[str, ast.Expr] | None = None,
    sentinel_placeholders: set[str] | None = None,
    query_type: str | None = None,
    spill_to_disk: bool = False,
    wait_timeout_seconds: float | None = None,
    serve_stale_grace_seconds: float | None = None,
) -> LazyComputationResult:
    """
    Ensure lazy-computed data exists for the given query and time range.

    This is the manual API for lazy computation. Unlike the automatic transformation,
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
        team: The team to create lazy-computed data for
        insert_query: A SELECT query, either a string template with {time_window_min} /
                      {time_window_max} placeholders, or a prebuilt SelectQuery AST using
                      ast.Placeholder nodes for those names.
        time_range_start: Start of the overall time range (inclusive)
        time_range_end: End of the overall time range (exclusive)
        ttl_seconds: How long before the data expires. Either:
                     - int: uniform TTL in seconds for all ranges (default 7 days)
                     - dict: maps date strings to TTL values. Keys are parsed using
                       relative_date_parse (e.g. "7d", "24h", "2026-02-15"). The
                       "default" key sets the fallback TTL. Uses team timezone.
        table: The target computation table (default "preaggregation_results")
        placeholders: Additional placeholder values to substitute into the query.
                      time_window_min and time_window_max are added automatically.
        sentinel_placeholders: Placeholder names to replace with fixed sentinel values
                      for hashing. Use this for placeholders whose values change between
                      requests (e.g. datetime.now()) but shouldn't invalidate the cache.
                      The real values are still used at INSERT time.
        wait_timeout_seconds: Wall-clock budget for the executor's compute-and-wait
                      loop (default DEFAULT_WAIT_TIMEOUT_SECONDS). The loop checks the
                      budget before starting each inline INSERT and while polling for
                      other requests' pending jobs, so a completed window always
                      persists as a READY job even when the overall call times out,
                      so repeated calls converge. Use a small value for user-facing
                      requests that have a cheap fallback path.
        serve_stale_grace_seconds: When set, requests that would otherwise compute
                      inline or wait are served from READY jobs expired within the
                      last N seconds (result comes back with `stale=True`). Only for
                      user-facing callers with a refresh mechanism (e.g. an hourly
                      warmer); background refreshers must leave this unset or they
                      would serve stale to themselves and never recompute.

    Returns:
        ComputationResult with job_ids that can be used to query the data

    Example:
        result = ensure_precomputed(
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
        # Use result.job_ids to query from the lazy-computed results table
    """
    base_placeholders = placeholders or {}
    _validate_no_reserved_placeholders(base_placeholders)

    if sentinel_placeholders:
        missing = sentinel_placeholders - set(base_placeholders)
        if missing:
            raise ValueError(
                f"sentinel_placeholders {missing} must also be present in placeholders "
                "so real values are available at INSERT time."
            )

    # Parse the query template with sentinel placeholders for stable hashing.
    # time_window_min/max are always sentinelized (managed by the executor).
    # Callers can opt additional placeholders into sentinelization via sentinel_placeholders.
    caller_sentinels: dict[str, ast.Expr] = {
        name: ast.Constant(value=f"__{name.upper()}__") for name in (sentinel_placeholders or set())
    }
    hash_placeholders: dict[str, ast.Expr] = {
        **base_placeholders,
        "time_window_min": ast.Constant(value="__TIME_WINDOW_MIN__"),
        "time_window_max": ast.Constant(value="__TIME_WINDOW_MAX__"),
        **caller_sentinels,
    }
    parsed_for_hash = _resolve_insert_query(insert_query, hash_placeholders)

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
        tag_kwargs: dict = {
            "client_query_id": str(job.id),
            "team_id": t.id,
            "precompute_window_start": str(job.time_range_start),
            "precompute_window_end": str(job.time_range_end),
        }
        if query_type:
            tag_kwargs["query_type"] = query_type
        with tags_context(**tag_kwargs):
            sync_execute(
                insert_sql,
                values,
                settings=_get_insert_settings(t.id, spill_to_disk=spill_to_disk),
            )

    # A caller can hand in a fully-built TtlSchedule (e.g. one carrying a max_window_days
    # cap) to bound job width — "switch the schedule"; otherwise parse int/dict as usual.
    ttl_schedule = (
        ttl_seconds if isinstance(ttl_seconds, TtlSchedule) else parse_ttl_schedule(ttl_seconds, team.timezone)
    )
    executor = LazyComputationExecutor(
        ttl_schedule=ttl_schedule,
        wait_timeout_seconds=wait_timeout_seconds if wait_timeout_seconds is not None else DEFAULT_WAIT_TIMEOUT_SECONDS,
        serve_stale_grace_seconds=serve_stale_grace_seconds,
    )
    return executor.execute(team, query_info, time_range_start, time_range_end, run_insert=_run_manual_insert)


def _resolve_insert_query(insert_query: str | ast.SelectQuery, placeholders: dict[str, ast.Expr]) -> ast.SelectQuery:
    """Resolve an insert query into a SelectQuery AST with its placeholders filled.

    String callers (web analytics, experiments) carry `{time_window_min/max}` as text; AST callers
    (conversion goals) carry `ast.Placeholder` nodes. `parse_select` substitutes placeholders via the
    same `replace_placeholders`, so both inputs resolve identically.
    """
    if isinstance(insert_query, str):
        resolved: ast.Expr = parse_select(insert_query, placeholders=placeholders)
    else:
        resolved = replace_placeholders(insert_query, placeholders)
    assert isinstance(resolved, ast.SelectQuery)
    return resolved


def _build_manual_insert_sql(
    team: Team,
    job: PreaggregationJob,
    insert_query: str | ast.SelectQuery,
    table: LazyComputationTable,
    base_placeholders: dict[str, ast.Expr] | None = None,
) -> tuple[str, dict]:
    """
    Build INSERT SQL for manual lazy computation.

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

    # Resolve the query with all placeholders — returns a fresh AST we can mutate
    query = _resolve_insert_query(insert_query, all_placeholders)
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

    # Print to SQL. Materialization is a system, team-scoped process with no request user, so bypass
    # warehouse access control to avoid failing closed in this userless context. Caveat: the native
    # pre-agg table this writes is later read WITHOUT warehouse RBAC, so materialization does not enforce
    # per-source access on reads — a user with dashboard access can see aggregates from warehouse sources
    # they can't query directly. Whether the pre-agg read should re-check source access is an open question.
    context = HogQLContext(
        team_id=team.id,
        team=team,
        enable_select_queries=True,
        limit_top_select=False,
        modifiers=create_default_modifiers_for_team(team),
        bypass_warehouse_access_control=True,
    )
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
