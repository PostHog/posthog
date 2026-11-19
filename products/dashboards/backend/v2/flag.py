from posthog.models.team import Team
from posthog.permissions import posthog_feature_flag_enabled

DASHBOARD_V2_FLAG = "dashboard-v2"


def dashboard_v2_enabled(team: Team, distinct_id: str) -> bool:
    return posthog_feature_flag_enabled(
        DASHBOARD_V2_FLAG,
        distinct_id,
        organization_id=team.organization_id,
        team_id=team.pk,
        only_evaluate_locally=True,
    )
