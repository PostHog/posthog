import structlog
import posthoganalytics

from posthog.models.team import Team

logger = structlog.get_logger(__name__)

SEARCH_V2_FLAG = "product-support-search-v2"


def is_search_v2_enabled(team: Team) -> bool:
    """Whether the indexed two-step ticket search path is enabled for this team."""
    # The flag is targeted by project group; release conditions can match on the project's `uuid`,
    # so it must be in group_properties — the backend SDK only sends what's listed here (unlike
    # posthog-js, which auto-attaches full group properties). Without it a uuid filter never matches.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SEARCH_V2_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id), "uuid": str(team.uuid)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        # A flag-service blip must not break ticket search. Fail closed: fall back to the
        # legacy search path.
        logger.warning("conversations: search v2 flag eval failed", team_id=team.id, exc_info=True)
        return False
