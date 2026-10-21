import structlog

from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

SNAPSHOT_FLAG = "data-modeling-snapshot-views"

logger = structlog.get_logger(__name__)


def snapshot_materialization_enabled(team_id: int) -> bool:
    """Fail closed while snapshot materialization is being rolled out."""
    try:
        team = Team.objects.only("organization_id").get(id=team_id)
        return feature_enabled_or_false(
            SNAPSHOT_FLAG,
            str(team_id),
            groups={"organization": str(team.organization_id), "project": str(team_id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team_id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("Failed to evaluate snapshot flag; keeping snapshot disabled", team_id=team_id)
        return False
