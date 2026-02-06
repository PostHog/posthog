import copy
import json
import time
import hashlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone as django_timezone

from clickhouse_driver.errors import ServerException

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE
from posthog.models.team import Team

from products.analytics_platform.backend.models import PreaggregationJob

# Default TTL for preaggregated data (how long before ClickHouse deletes it)
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# Buffer time before expiry when we stop using a job.
# This prevents race conditions where we try to query data that ClickHouse
# is about to delete or has just deleted.
EXPIRY_BUFFER_SECONDS = 1 * 60 * 60  # 1 hour

# Waiting configuration for pending jobs
DEFAULT_WAIT_TIMEOUT_SECONDS = 180  # 3 minutes
DEFAULT_POLL_INTERVAL_SECONDS = 1.0  # Poll every 1 second
DEFAULT_MAX_ATTEMPTS = 3  # Maximum retry attempts for failed jobs

# Heartbeat configuration - keeps job marked as "alive" during long INSERTs
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30.0  # Update updated_at every 30 seconds

# Threshold for detecting stale PENDING jobs (executor may have crashed)
# With 30s heartbeat, 2 minutes = 4 missed heartbeats before considering dead
DEFAULT_STALE_PENDING_THRESHOLD_SECONDS = 120  # 2 minutes

# ClickHouse error codes that should NOT be retried (fatal errors)
FATAL_CLICKHOUSE_ERROR_CODES = frozenset(
    {
        62,  # SYNTAX_ERROR
        43,  # ILLEGAL_TYPE_OF_ARGUMENT
        53,  # TYPE_MISMATCH
        46,  # UNKNOWN_FUNCTION
        47,  # UNKNOWN_IDENTIFIER
        60,  # UNKNOWN_TABLE
        16,  # NO_SUCH_COLUMN_IN_TABLE
    }
)


def is_fatal_error(error: Exception) -> bool:
    """
    Check if an error should NOT be retried.

    Fatal errors include:
    - Network/connection errors (can't reach ClickHouse)
    - ClickHouse syntax errors, type mismatches, unknown identifiers
    """
    # Network/connection errors - can't reach ClickHouse
    if isinstance(error, (ConnectionError, OSError, TimeoutError)):
        return True

    # ClickHouse server errors with fatal codes
    if isinstance(error, ServerException) and error.code in FATAL_CLICKHOUSE_ERROR_CODES:
        return True

    # Check wrapped errors (e.g., from wrap_query_error)
    if error.__cause__ is not None:
        return is_fatal_error(error.__cause__)

    return False


@contextmanager
def heartbeat_while_running(
    job: "PreaggregationJob",
    interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
):
    """
    Update job.updated_at periodically while the wrapped code runs.

    This prevents the job from being marked as stale while a long INSERT
    is still executing. The heartbeat stops when the context exits
    (whether success or failure).
    """
    stop_event = threading.Event()

    def heartbeat_loop():
        while not stop_event.wait(timeout=interval_seconds):
            # Atomic update - only if job is still PENDING
            PreaggregationJob.objects.filter(
                id=job.id,
                status=PreaggregationJob.Status.PENDING,
            ).update(updated_at=django_timezone.now())

    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    try:
        yield
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=5.0)  # Don't block forever if thread is stuck


class PreaggregationTable(StrEnum):
    """Allowed target tables for preaggregation results."""

    PREAGGREGATION_RESULTS = "preaggregation_results"


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
    job_ids: list
    errors: list[str] = field(default_factory=list)


@dataclass
class WaitResult:
    """Result of waiting for pending preaggregation jobs."""

    success: bool
    ready_job_ids: list
    failed_jobs: list  # List of PreaggregationJob objects that permanently failed
    timed_out: bool = False


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
    if end.hour > 0 or end.minute > 0 or end.second > 0:
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

    Excludes jobs that are expired or about to expire (within EXPIRY_BUFFER_SECONDS).
    """
    # Calculate the minimum expires_at we'll accept (now + buffer)
    min_expires_at = django_timezone.now() + timedelta(seconds=EXPIRY_BUFFER_SECONDS)

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
        # Check if this job overlaps with any already-selected job
        has_overlap = False
        for selected_job in selected:
            if _intervals_overlap(
                job.time_range_start,
                job.time_range_end,
                selected_job.time_range_start,
                selected_job.time_range_end,
            ):
                has_overlap = True
                break

        if not has_overlap:
            selected.append(job)

    return selected


def find_missing_contiguous_windows(
    existing_jobs: list[PreaggregationJob],
    start_timestamp: datetime,
    end_timestamp: datetime,
) -> list[tuple[datetime, datetime]]:
    """
    Find which daily windows are not covered by existing READY jobs,
    then merge contiguous missing windows into ranges.

    For example, if the range is Jan 1-4 and a READY job exists for Jan 2,
    this returns: [(Jan 1, Jan 2), (Jan 3, Jan 4)]

    If no jobs exist for Jan 1-4, it returns: [(Jan 1, Jan 4)]
    """
    # Step 1: Generate daily windows for the range
    daily_windows = get_daily_windows(start_timestamp, end_timestamp)

    # Step 2: Find missing daily windows
    missing = []
    for window_start, window_end in daily_windows:
        # Check if this window is covered by any READY job
        is_covered = False
        for job in existing_jobs:
            if (
                job.status == PreaggregationJob.Status.READY
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
    context = HogQLContext(team_id=team.id, team=team, enable_select_queries=True)
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
    """
    Run the INSERT query to populate preaggregation results in ClickHouse.

    Uses a heartbeat to update job.updated_at periodically, preventing the job
    from being marked as stale during long-running INSERTs.
    """
    assert job.expires_at is not None

    insert_sql, values = build_preaggregation_insert_sql(
        team=team,
        job_id=str(job.id),
        select_query=query_info.query,
        time_range_start=job.time_range_start,
        time_range_end=job.time_range_end,
        expires_at=job.expires_at,
    )

    with heartbeat_while_running(job):
        sync_execute(insert_sql, values)


class PreaggregationExecutor:
    """
    Executes preaggregation jobs with configurable waiting behavior.

    Settings can be configured at initialization:
    - wait_for_pending: Whether to wait for pending jobs (default True)
    - wait_timeout_seconds: Max time to wait for pending jobs (default 180s)
    - poll_interval_seconds: How often to check job status (default 1s)
    - max_attempts: Max retry attempts for failed jobs (default 3)
    - ttl_seconds: How long preaggregated data persists (default 7 days)
    - stale_pending_threshold_seconds: How long before a PENDING job is considered stale
    """

    def __init__(
        self,
        wait_for_pending: bool = True,
        wait_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        stale_pending_threshold_seconds: float = DEFAULT_STALE_PENDING_THRESHOLD_SECONDS,
    ):
        self.wait_for_pending = wait_for_pending
        self.wait_timeout_seconds = wait_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_attempts = max_attempts
        self.ttl_seconds = ttl_seconds
        self.stale_pending_threshold_seconds = stale_pending_threshold_seconds

    def execute(
        self,
        team: Team,
        query_info: QueryInfo,
        start: datetime,
        end: datetime,
    ) -> PreaggregationResult:
        """
        Execute preaggregation jobs for the given query and time range.

        1. Hash the query to get a stable identifier
        2. Find existing jobs (READY and PENDING)
        3. Wait for pending jobs if enabled
        4. Identify missing time windows
        5. Create and execute jobs for missing ranges
        6. Return job IDs for the combiner query
        """
        errors: list[str] = []
        job_ids: list = []

        query_hash = compute_query_hash(query_info)

        existing_jobs = find_existing_jobs(team, query_hash, start, end)

        # Separate READY and PENDING jobs
        ready_jobs = [j for j in existing_jobs if j.status == PreaggregationJob.Status.READY]
        pending_jobs = [j for j in existing_jobs if j.status == PreaggregationJob.Status.PENDING]

        # Wait for pending jobs if enabled
        if self.wait_for_pending and pending_jobs:
            wait_result = self._wait_for_pending_jobs(team, pending_jobs, query_info)

            # Add successfully completed jobs to ready list
            for job_id in wait_result.ready_job_ids:
                job = PreaggregationJob.objects.get(id=job_id)
                ready_jobs.append(job)

            # Report failed jobs as errors
            for failed_job in wait_result.failed_jobs:
                errors.append(f"Job {failed_job.id} failed: {failed_job.error}")

            if wait_result.timed_out:
                errors.append("Timeout waiting for pending jobs")

        # Filter to remove overlapping jobs (keep most recent)
        ready_jobs = filter_overlapping_jobs(ready_jobs)

        for existing_job in ready_jobs:
            job_ids.append(existing_job.id)

        # Find missing windows merged into contiguous ranges
        missing_ranges = find_missing_contiguous_windows(ready_jobs, start, end)

        if not missing_ranges and not job_ids:
            return PreaggregationResult(ready=True, job_ids=[])

        for range_start, range_end in missing_ranges:
            new_job: PreaggregationJob | None = None
            try:
                new_job = create_preaggregation_job(team, query_hash, range_start, range_end, self.ttl_seconds)
                run_preaggregation_insert(team, new_job, query_info)

                new_job.status = PreaggregationJob.Status.READY
                new_job.computed_at = django_timezone.now()
                new_job.save()

                job_ids.append(new_job.id)

            except Exception as e:
                if new_job is not None:
                    new_job.status = PreaggregationJob.Status.FAILED
                    new_job.error = str(e)
                    new_job.save()
                errors.append(f"Failed to create preaggregation for {range_start}-{range_end}: {e}")

        # Ready if no errors (all missing ranges were successfully created)
        all_ready = len(errors) == 0

        return PreaggregationResult(ready=all_ready, job_ids=job_ids, errors=errors)

    def _try_create_replacement_job(
        self,
        failed_job: PreaggregationJob,
    ) -> PreaggregationJob | None:
        """
        Try to create a replacement job for a failed job.

        Uses the same range as the failed job. Returns the new job if created,
        or None if another waiter already created a replacement (IntegrityError).
        """
        try:
            # Use a savepoint to properly handle IntegrityError without
            # breaking the outer transaction (important for test compatibility)
            with transaction.atomic():
                return PreaggregationJob.objects.create(
                    team=failed_job.team,
                    query_hash=failed_job.query_hash,
                    time_range_start=failed_job.time_range_start,
                    time_range_end=failed_job.time_range_end,
                    status=PreaggregationJob.Status.PENDING,
                    expires_at=django_timezone.now() + timedelta(seconds=self.ttl_seconds),
                )
        except IntegrityError:
            # Another waiter created a replacement first - this is expected
            return None

    def _find_pending_replacement(
        self,
        failed_job: PreaggregationJob,
    ) -> PreaggregationJob | None:
        """Find the pending replacement job for a failed job."""
        return PreaggregationJob.objects.filter(
            team=failed_job.team,
            query_hash=failed_job.query_hash,
            time_range_start=failed_job.time_range_start,
            time_range_end=failed_job.time_range_end,
            status=PreaggregationJob.Status.PENDING,
        ).first()

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
        return updated > 0

    def _wait_for_pending_jobs(
        self,
        team: Team,
        pending_jobs: list[PreaggregationJob],
        query_info: QueryInfo,
    ) -> WaitResult:
        """
        Wait for pending jobs to complete, handling failures with retry logic.

        If a job fails and this waiter wins the race to create a replacement, execute the retry.
        If another waiter wins, continue waiting for their replacement.
        If max_attempts exceeded, mark as permanently failed.

        Attempt tracking is per-waiter (not stored on jobs), so new queries get fresh attempts.

        Returns WaitResult indicating success/failure and which jobs are ready.
        """
        start_time = time.monotonic()
        # Track jobs we're waiting for: maps tracking key -> (current job, attempt count)
        # The tracking key stays constant even as the job changes on replacement
        waiting_for: dict = {job.id: {"job": job, "attempts": 0} for job in pending_jobs}
        ready_job_ids: list = []
        failed_jobs: list[PreaggregationJob] = []

        while waiting_for:
            elapsed = time.monotonic() - start_time
            if elapsed >= self.wait_timeout_seconds:
                return WaitResult(
                    success=False,
                    ready_job_ids=ready_job_ids,
                    failed_jobs=failed_jobs,
                    timed_out=True,
                )

            # Check status of all jobs we're waiting for
            job_ids_to_check = [entry["job"].id for entry in waiting_for.values()]
            jobs_by_id = {job.id: job for job in PreaggregationJob.objects.filter(id__in=job_ids_to_check)}

            for tracking_key, entry in list(waiting_for.items()):
                job = jobs_by_id.get(entry["job"].id)
                if job is None:
                    continue

                if job.status == PreaggregationJob.Status.READY:
                    ready_job_ids.append(job.id)
                    del waiting_for[tracking_key]

                elif job.status == PreaggregationJob.Status.FAILED:
                    # Each failed job counts as an attempt, regardless of who creates the replacement
                    entry["attempts"] += 1

                    if entry["attempts"] >= self.max_attempts:
                        # This waiter has exceeded their attempt budget
                        failed_jobs.append(job)
                        del waiting_for[tracking_key]
                    else:
                        # Try to create a replacement job
                        replacement = self._try_create_replacement_job(job)
                        if replacement is not None:
                            # We won the race - execute the replacement
                            try:
                                run_preaggregation_insert(team, replacement, query_info)
                                replacement.status = PreaggregationJob.Status.READY
                                replacement.computed_at = django_timezone.now()
                                replacement.save()
                                ready_job_ids.append(replacement.id)
                                del waiting_for[tracking_key]
                            except Exception as e:
                                replacement.status = PreaggregationJob.Status.FAILED
                                replacement.error = str(e)
                                replacement.save()

                                if is_fatal_error(e):
                                    # Fatal error - don't retry, fail immediately
                                    failed_jobs.append(replacement)
                                    del waiting_for[tracking_key]
                                else:
                                    # Retryable error - wait for replacement (might be retried again)
                                    entry["job"] = replacement
                        else:
                            # Another waiter created a replacement - find it and wait for it
                            existing_replacement = self._find_pending_replacement(job)
                            if existing_replacement is not None:
                                entry["job"] = existing_replacement
                            # else: Edge case - re-check on next iteration

                elif job.status == PreaggregationJob.Status.PENDING:
                    # Check if job is stale (executor may have crashed)
                    stale_threshold = django_timezone.now() - timedelta(seconds=self.stale_pending_threshold_seconds)
                    if job.updated_at < stale_threshold:
                        # Try to mark as failed - triggers replacement flow on next iteration
                        self._try_mark_stale_job_as_failed(job)
                        # Either way, status will be checked on next iteration
                    # else: Still waiting - keep polling

            if waiting_for:
                remaining_timeout = self.wait_timeout_seconds - (time.monotonic() - start_time)
                sleep_time = min(self.poll_interval_seconds, remaining_timeout)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        return WaitResult(
            success=len(failed_jobs) == 0,
            ready_job_ids=ready_job_ids,
            failed_jobs=failed_jobs,
            timed_out=False,
        )


def execute_preaggregation_jobs(
    team: Team,
    query_info: QueryInfo,
    start: datetime,
    end: datetime,
) -> PreaggregationResult:
    """
    Backward-compatible function for executing preaggregation jobs.

    Uses PreaggregationExecutor with default settings.
    """
    executor = PreaggregationExecutor()
    return executor.execute(team, query_info, start, end)


def ensure_preaggregated(
    team: Team,
    insert_query: str,
    time_range_start: datetime,
    time_range_end: datetime,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
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

    The following placeholders are added automatically per-job:
    - {time_window_min}: Start of the job's time window (datetime)
    - {time_window_max}: End of the job's time window (datetime)

    Your query MUST use these placeholders to filter data to the correct time range.

    The query should include (in order after auto-added columns):
    - time_window_start: The time bucket (e.g., toStartOfDay(timestamp))
    - expires_at: When the data expires (use a constant or expression)
    - ... additional columns as needed by the table schema

    Args:
        team: The team to create preaggregation for
        insert_query: A SELECT query string with placeholders. Use {time_window_min}
                      and {time_window_max} for time filtering.
        time_range_start: Start of the overall time range (inclusive)
        time_range_end: End of the overall time range (exclusive)
        ttl_seconds: How long before the data expires (default 7 days)
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
                    now() + INTERVAL 7 DAY as expires_at,
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
        )
        # Use result.job_ids to query from preaggregation_results
    """
    base_placeholders = placeholders or {}

    # Validate that reserved placeholders are not provided
    reserved_placeholders = {"time_window_min", "time_window_max"}
    conflicting = reserved_placeholders & set(base_placeholders.keys())
    if conflicting:
        raise ValueError(
            f"Cannot use reserved placeholder names: {conflicting}. "
            "time_window_min and time_window_max are automatically added per-job."
        )

    # Parse the query template (without time placeholders) for hashing
    # We use sentinel values that will produce a stable hash
    hash_placeholders = {
        **base_placeholders,
        "time_window_min": ast.Constant(value="__TIME_WINDOW_MIN__"),
        "time_window_max": ast.Constant(value="__TIME_WINDOW_MAX__"),
    }
    parsed_for_hash = parse_select(insert_query, placeholders=hash_placeholders)
    assert isinstance(parsed_for_hash, ast.SelectQuery)

    # Create QueryInfo for hashing (timezone from team)
    query_info = QueryInfo(
        query=parsed_for_hash,
        table=table,
        timezone=team.timezone,
    )

    query_hash = compute_query_hash(query_info)

    # Find existing jobs
    existing_jobs = find_existing_jobs(team, query_hash, time_range_start, time_range_end)

    # Filter to only READY jobs, then remove overlaps (keeping most recent)
    ready_jobs = [j for j in existing_jobs if j.status == PreaggregationJob.Status.READY]
    ready_jobs = filter_overlapping_jobs(ready_jobs)

    job_ids: list = [job.id for job in ready_jobs]

    # Find missing windows
    missing_ranges = find_missing_contiguous_windows(ready_jobs, time_range_start, time_range_end)

    if not missing_ranges and not job_ids:
        return PreaggregationResult(ready=True, job_ids=[])

    errors: list[str] = []

    for range_start, range_end in missing_ranges:
        new_job: PreaggregationJob | None = None
        try:
            new_job = create_preaggregation_job(team, query_hash, range_start, range_end, ttl_seconds=ttl_seconds)

            # Build and execute the INSERT query with job-specific time placeholders
            insert_sql, values = _build_manual_insert_sql(
                team=team,
                job=new_job,
                insert_query=insert_query,
                table=table,
                base_placeholders=base_placeholders,
            )
            sync_execute(insert_sql, values)

            new_job.status = PreaggregationJob.Status.READY
            new_job.computed_at = django_timezone.now()
            new_job.save()

            job_ids.append(new_job.id)

        except Exception as e:
            if new_job is not None:
                new_job.status = PreaggregationJob.Status.FAILED
                new_job.error = str(e)
                new_job.save()
            errors.append(f"Failed to create preaggregation for {range_start}-{range_end}: {e}")

    all_ready = len(errors) == 0
    return PreaggregationResult(ready=all_ready, job_ids=job_ids, errors=errors)


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
    then adds team_id and job_id to the SELECT list.

    The query should use {time_window_min} and {time_window_max} placeholders
    for time filtering - these are substituted with the job's time range.
    """
    # Validate that reserved placeholders are not provided
    if base_placeholders:
        reserved_placeholders = {"time_window_min", "time_window_max"}
        conflicting = reserved_placeholders & set(base_placeholders.keys())
        if conflicting:
            raise ValueError(
                f"Cannot use reserved placeholder names: {conflicting}. "
                "time_window_min and time_window_max are automatically added per-job."
            )

    # Build placeholders with job-specific time values
    all_placeholders = {
        **(base_placeholders or {}),
        "time_window_min": ast.Constant(value=job.time_range_start),
        "time_window_max": ast.Constant(value=job.time_range_end),
    }

    # Parse the query with all placeholders
    parsed = parse_select(insert_query, placeholders=all_placeholders)
    assert isinstance(parsed, ast.SelectQuery)

    # Deep copy to avoid issues
    query = copy.deepcopy(parsed)
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

    # Print to SQL
    context = HogQLContext(team_id=team.id, team=team, enable_select_queries=True)
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
