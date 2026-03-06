import dagster

from posthog.dags.common.health.types import HealthCheckResult
from posthog.exceptions_capture import capture_exception


def _validate_batch_output(
    issues_by_team: dict[int, list[HealthCheckResult]],
    valid_team_ids: set[int],
    kind: str,
    context: dagster.OpExecutionContext,
) -> dict[int, list[HealthCheckResult]]:
    validated: dict[int, list[HealthCheckResult]] = {}
    for team_id, results in issues_by_team.items():
        if team_id not in valid_team_ids:
            err = ValueError(f"Health check '{kind}': detector returned team_id={team_id} not in input batch")
            context.log.warning(str(err))
            capture_exception(err, {"health_check_kind": kind, "team_id": team_id})
            continue
        if not isinstance(results, list) or len(results) == 0:
            context.log.warning(f"Health check '{kind}': empty/invalid results for team_id={team_id}, ignoring")
            continue
        valid_results = [r for r in results if isinstance(r, HealthCheckResult)]
        if len(valid_results) != len(results):
            context.log.warning(
                f"Health check '{kind}': {len(results) - len(valid_results)} non-HealthCheckResult items "
                f"for team_id={team_id}"
            )
        if valid_results:
            validated[team_id] = valid_results
    return validated
