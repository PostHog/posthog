import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

# Selects the per-source fanout workflow for new account-property segment syncs. The flag is
# created default-off, so an absent flag keeps every team on the legacy workflow.
ACCOUNT_PROPERTY_SYNC_FANOUT_FLAG = "warehouse-account-property-sync-fanout"


def account_property_sync_fanout_enabled(team_id: int) -> bool:
    """Whether new segment syncs for the team use the fanout workflow, targeted by the team's organization.

    Fails closed: an unknown team, a missing flag, or any lookup or flag-service error selects the legacy workflow.
    """
    try:
        organization_id = str(Team.objects.only("organization_id").get(id=team_id).organization_id)
        enabled = posthoganalytics.feature_enabled(
            ACCOUNT_PROPERTY_SYNC_FANOUT_FLAG,
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Team.DoesNotExist:
        return False
    except Exception as error:
        capture_exception(error)
        return False
    return enabled is True
