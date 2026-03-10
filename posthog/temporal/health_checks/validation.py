import structlog

from posthog.exceptions_capture import capture_exception
from posthog.temporal.health_checks.models import HealthCheckResult

logger = structlog.get_logger(__name__)


def _validate_batch_output(
    issues_by_team: dict[int, list[HealthCheckResult]],
    valid_team_ids: set[int],
    kind: str,
) -> tuple[dict[int, list[HealthCheckResult]], int]:
    validated: dict[int, list[HealthCheckResult]] = {}
    teams_dropped = 0
    for team_id, results in issues_by_team.items():
        if team_id not in valid_team_ids:
            err = ValueError(f"Health check '{kind}': detector returned team_id={team_id} not in input batch")
            logger.warning("detector returned team_id not in input batch", kind=kind, team_id=team_id)
            capture_exception(err, {"health_check_kind": kind, "team_id": team_id})
            teams_dropped += 1
            continue
        if not isinstance(results, list) or len(results) == 0:
            logger.warning("empty or invalid results, ignoring", kind=kind, team_id=team_id)
            teams_dropped += 1
            continue
        valid_results = [r for r in results if isinstance(r, HealthCheckResult)]
        if len(valid_results) != len(results):
            logger.warning(
                "non-HealthCheckResult items found",
                kind=kind,
                team_id=team_id,
                invalid_count=len(results) - len(valid_results),
            )
        if valid_results:
            validated[team_id] = valid_results
        else:
            teams_dropped += 1
    return validated, teams_dropped
