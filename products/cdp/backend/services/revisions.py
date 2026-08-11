import structlog
import posthoganalytics

from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

DESTINATIONS_REVISIONS_FLAG = "destinations-revisions"


def use_destinations_revisions(team: Team) -> bool:
    """Gates the draft → review → publish cycle on enabled functions; off means today's behavior
    (every edit lands straight on the live config that workers execute).

    A raised exception (Redis/HyperCache blip, network glitch, SDK bug) is treated as "flag off" so
    the flag is a kill switch: edits keep applying live, exactly as they did before this shipped.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                DESTINATIONS_REVISIONS_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
            )
        )
    except Exception:
        logger.warning(
            "cdp.revisions.feature_flag_check_failed_defaulting_off",
            team_id=team.id,
            flag=DESTINATIONS_REVISIONS_FLAG,
            exc_info=True,
        )
        return False
