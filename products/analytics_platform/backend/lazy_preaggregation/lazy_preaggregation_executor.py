import copy
import json
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from django.utils import timezone as django_timezone

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE
from posthog.models.team import Team

from products.analytics_platform.backend.models import PreaggregationJob


@dataclass
class QueryInfo:
    """Normalized query information for preaggregation matching."""

    query: ast.SelectQuery
    timezone: str = "UTC"
    breakdown_fields: list[str] = field(default_factory=list)


@dataclass
class PreaggregationResult:
    """Result of executing preaggregation jobs."""

    ready: bool
    job_ids: list
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
    """
    return list(
        PreaggregationJob.objects.filter(
            team=team,
            query_hash=query_hash,
            time_range_start__lt=end,
            time_range_end__gt=start,
            status__in=[PreaggregationJob.Status.READY, PreaggregationJob.Status.PENDING],
        ).order_by("time_range_start")
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
) -> PreaggregationJob:
    """Create a new preaggregation job in PENDING status."""
    return PreaggregationJob.objects.create(
        team=team,
        query_hash=query_hash,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        status=PreaggregationJob.Status.PENDING,
    )


def build_preaggregation_insert_sql(
    team: Team,
    job_id: str,
    select_query: ast.SelectQuery,
    time_range_start: datetime,
    time_range_end: datetime,
) -> tuple[str, dict]:
    """
    Build the INSERT ... SELECT SQL for populating preaggregation results.

    Takes a SelectQuery AST with 3 expressions (time_window_start, breakdown_value, uniq_exact_state)
    and prepends team_id and appends job_id, then adds a date range filter to the WHERE clause.
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

    # Append job_id as the last expression
    job_id_expr = ast.Alias(
        alias="job_id",
        expr=ast.Call(name="toUUID", args=[ast.Constant(value=job_id)]),
    )
    query.select.append(job_id_expr)

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
    job_id
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
    """
    insert_sql, values = build_preaggregation_insert_sql(
        team=team,
        job_id=str(job.id),
        select_query=query_info.query,
        time_range_start=job.time_range_start,
        time_range_end=job.time_range_end,
    )
    sync_execute(insert_sql, values)


def execute_preaggregation_jobs(
    team: Team,
    query_info: QueryInfo,
    start: datetime,
    end: datetime,
) -> PreaggregationResult:
    """
    Main orchestration function for preaggregation jobs.

    1. Hash the query to get a stable identifier
    2. Find existing jobs for this query
    3. Filter out overlapping jobs (keep most recent)
    4. Identify missing time windows (merged into contiguous ranges)
    5. Create and execute jobs for missing ranges
    6. Return job IDs for the combiner query
    """
    errors: list[str] = []
    job_ids: list = []

    query_hash = compute_query_hash(query_info)

    existing_jobs = find_existing_jobs(team, query_hash, start, end)

    # Filter to only READY jobs, then remove overlaps (keeping most recent)
    ready_jobs = [j for j in existing_jobs if j.status == PreaggregationJob.Status.READY]
    ready_jobs = filter_overlapping_jobs(ready_jobs)

    for existing_job in ready_jobs:
        job_ids.append(existing_job.id)

    # Find missing windows merged into contiguous ranges
    # Use filtered ready_jobs so coverage matches what we'll actually return
    missing_ranges = find_missing_contiguous_windows(ready_jobs, start, end)

    if not missing_ranges and not job_ids:
        return PreaggregationResult(ready=True, job_ids=[])

    for range_start, range_end in missing_ranges:
        new_job: PreaggregationJob | None = None
        try:
            new_job = create_preaggregation_job(team, query_hash, range_start, range_end)
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
