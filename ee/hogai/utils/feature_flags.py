import posthoganalytics

from posthog.models import Team, User


def has_agent_modes_feature_flag(team: Team, user: User) -> bool:
    return posthoganalytics.feature_enabled(
        "phai-agent-modes",
        str(user.distinct_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )
