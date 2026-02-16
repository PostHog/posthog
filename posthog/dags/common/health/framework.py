from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, Union, cast, overload

import dagster

from posthog.dags.common.common import JobOwners, check_for_concurrent_runs
from posthog.dags.common.health.processing import _process_batch_detection, _process_per_team_detection
from posthog.dags.common.health.types import (
    BatchDetectFn,
    BatchResult,
    HealthCheckDefinition,
    HealthCheckThresholdExceeded,
    TeamDetectFn,
)
from posthog.dags.common.ops import get_all_team_ids_op

_REGISTERED_KINDS: dict[str, str] = {}

_default_retry_policy: dagster.RetryPolicy = dagster.RetryPolicy(
    max_retries=2,
    delay=30,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.PLUS_MINUS,
)


def get_registered_kinds() -> Mapping[str, str]:
    return MappingProxyType(_REGISTERED_KINDS)


def _reset_registry() -> None:
    """Clear the kind registry. For test use only."""
    _REGISTERED_KINDS.clear()


def _to_batch_dagster_metadata(result: BatchResult, teams_per_second: float) -> dict[str, dagster.MetadataValue]:
    return {
        "detect_duration_seconds": dagster.MetadataValue.float(result.detect_duration),
        "db_write_duration_seconds": dagster.MetadataValue.float(result.db_write_duration),
        "resolve_duration_seconds": dagster.MetadataValue.float(result.resolve_duration),
        "total_duration_seconds": dagster.MetadataValue.float(result.total_duration),
        "teams_per_second": dagster.MetadataValue.float(teams_per_second),
        "batch_size": dagster.MetadataValue.int(result.batch_size),
        "issues_upserted": dagster.MetadataValue.int(result.issues_upserted),
        "issues_resolved": dagster.MetadataValue.int(result.issues_resolved),
        "teams_with_issues": dagster.MetadataValue.int(result.teams_with_issues),
        "teams_healthy": dagster.MetadataValue.int(result.teams_healthy),
        "teams_failed": dagster.MetadataValue.int(result.teams_failed),
        "teams_skipped": dagster.MetadataValue.int(result.teams_skipped),
    }


def _to_aggregate_dagster_metadata(totals: BatchResult, teams_per_second: float) -> dict[str, dagster.MetadataValue]:
    return {
        "total_teams": dagster.MetadataValue.int(totals.batch_size),
        "total_issues_upserted": dagster.MetadataValue.int(totals.issues_upserted),
        "total_issues_resolved": dagster.MetadataValue.int(totals.issues_resolved),
        "total_teams_with_issues": dagster.MetadataValue.int(totals.teams_with_issues),
        "total_teams_healthy": dagster.MetadataValue.int(totals.teams_healthy),
        "total_teams_failed": dagster.MetadataValue.int(totals.teams_failed),
        "total_teams_skipped": dagster.MetadataValue.int(totals.teams_skipped),
        "total_duration_seconds": dagster.MetadataValue.float(float(totals.total_duration)),
        "teams_per_second": dagster.MetadataValue.float(float(teams_per_second)),
    }


def _get_teams_per_second(result: BatchResult) -> float:
    return result.batch_size / result.total_duration if result.total_duration > 0 else 0


def _create_check_batch_op(
    name: str,
    kind: str,
    detect_fn: Union[BatchDetectFn, TeamDetectFn],
    per_team: bool,
) -> dagster.OpDefinition:
    @dagster.op(name=f"{name}_check_batch", retry_policy=_default_retry_policy)
    def check_batch_op(context: dagster.OpExecutionContext, team_ids: list[int]) -> BatchResult:
        if per_team:
            result = _process_per_team_detection(team_ids, kind, cast(TeamDetectFn, detect_fn), context)
        else:
            result = _process_batch_detection(team_ids, kind, cast(BatchDetectFn, detect_fn), context)

        teams_per_second = _get_teams_per_second(result)

        context.add_output_metadata(_to_batch_dagster_metadata(result, teams_per_second))

        return result

    return check_batch_op


def _aggregate_results(
    results: list[BatchResult],
    kind: str,
    not_processed_threshold: float,
    context: dagster.OpExecutionContext,
) -> None:
    totals = BatchResult()
    for r in results:
        totals += r

    teams_per_second = _get_teams_per_second(totals)

    context.log.info(
        f"Health check '{kind}' completed: {totals.batch_size:,} teams in {totals.total_duration:.0f}s "
        f"({teams_per_second:.0f} teams/sec)\n"
        f"  Issues: {totals.issues_upserted:,} upserted, {totals.issues_resolved:,} resolved\n"
        f"  Teams: {totals.teams_with_issues:,} with issues, {totals.teams_healthy:,} healthy, "
        f"{totals.teams_skipped:,} skipped, {totals.teams_failed:,} failed"
    )

    context.add_output_metadata(_to_aggregate_dagster_metadata(totals, teams_per_second))

    if totals.batch_size > 0:
        not_processed = totals.teams_skipped + totals.teams_failed
        not_processed_rate = not_processed / totals.batch_size

        if not_processed_rate > not_processed_threshold:
            raise HealthCheckThresholdExceeded(
                f"Health check '{kind}': {not_processed:,}/{totals.batch_size:,} teams not processed "
                f"({not_processed_rate:.1%}), exceeds threshold {not_processed_threshold:.1%} "
                f"(skipped={totals.teams_skipped:,}, failed={totals.teams_failed:,})"
            )


def _create_aggregate_op(
    name: str,
    kind: str,
    not_processed_threshold: float,
) -> dagster.OpDefinition:
    @dagster.op(name=f"{name}_aggregate")
    def aggregate_op(context: dagster.OpExecutionContext, results: list[BatchResult]) -> None:
        _aggregate_results(results, kind, not_processed_threshold, context)

    return aggregate_op


@overload
def create_health_check(
    name: str,
    kind: str,
    detect_fn: BatchDetectFn,
    owner: JobOwners,
    *,
    schedule: str | None = ...,
    batch_size: int = ...,
    max_concurrent: int = ...,
    not_processed_threshold: float = ...,
) -> HealthCheckDefinition: ...


@overload
def create_health_check(
    name: str,
    kind: str,
    detect_fn: TeamDetectFn,
    owner: JobOwners,
    *,
    per_team: Literal[True],
    schedule: str | None = ...,
    batch_size: int = ...,
    max_concurrent: int = ...,
    not_processed_threshold: float = ...,
) -> HealthCheckDefinition: ...


def create_health_check(
    name: str,
    kind: str,
    detect_fn: Union[BatchDetectFn, TeamDetectFn],
    owner: JobOwners,
    *,
    per_team: bool = False,
    schedule: str | None = None,
    batch_size: int = 1000,
    max_concurrent: int = 5,
    not_processed_threshold: float = 0.1,
) -> HealthCheckDefinition:
    """Create a complete health check pipeline as a Dagster job.

    Args:
        name: Unique name for the health check (used in Dagster op/job names).
        kind: The health issue kind string written to the health_issues table.
        detect_fn: Function used to detect the health issue.
        owner: The team that owns this health check for Slack alert routing.
        per_team: If `True`, `detect_fn` is called once per team with fault isolation and a
            single team's exception is caught and logged without affecting other teams.
            If `False` (default), `detect_fn` receives a batch of team IDs in a single call,
            which is more efficient but means an unhandled exception fails the entire batch.
            Use `per_team=True` when `detect_fn` may raise for individual teams.
            Use `per_team=False` when the detection logic is a single bulk query.
        schedule: Optional cron expression for scheduling.
        batch_size: Number of team IDs per batch.
        max_concurrent: Maximum parallel batch operations.
        not_processed_threshold: Fail if this fraction of teams are skipped or failed.

    Returns:
        HealthCheckDefinition
    """
    existing = _REGISTERED_KINDS.get(kind)
    if existing is not None and existing != name:
        raise ValueError(f"Health check kind '{kind}' already registered by '{existing}'")
    _REGISTERED_KINDS[kind] = name

    batch_op = _create_check_batch_op(name, kind, detect_fn, per_team)
    aggregate_op = _create_aggregate_op(name, kind, not_processed_threshold)

    job_config = {
        "ops": {
            "get_all_team_ids_op": {
                "config": {
                    "batch_size": batch_size,
                }
            }
        }
    }

    @dagster.job(
        name=f"{name}_health_check_job",
        description=f"Health check: {kind}",
        executor_def=dagster.multiprocess_executor.configured({"max_concurrent": max_concurrent}),
        tags={"owner": owner.value},
        config=job_config,
    )
    def health_check_job():
        team_batches = get_all_team_ids_op()
        results = team_batches.map(batch_op)
        aggregate_op(results.collect())

    schedule_def = None
    if schedule is not None:

        @dagster.schedule(
            cron_schedule=schedule,
            job=health_check_job,
            execution_timezone="UTC",
            name=f"{name}_health_check_schedule",
            tags={"owner": owner.value},
        )
        def health_check_schedule(context: dagster.ScheduleEvaluationContext):
            skip_reason = check_for_concurrent_runs(context, tags={})
            if skip_reason:
                return skip_reason
            return dagster.RunRequest(run_config=job_config)

        schedule_def = health_check_schedule

    return HealthCheckDefinition(job=health_check_job, schedule=schedule_def)
