"""Rollout gates for subscription delivery history (API + Temporal)."""

import posthoganalytics

from posthog.constants import HACKATHONS_SUBSCRIPTIONS_FEATURE_FLAG_KEY
from posthog.exceptions_capture import capture_exception


def _team_feature_enabled(flag_key: str, team_id: int) -> bool:
    from posthog.models import Team

    try:
        team = Team.objects.only("uuid", "organization_id", "id").get(pk=team_id)
    except Team.DoesNotExist:
        return False

    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag_key,
                str(team.uuid),
                groups={
                    "organization": str(team.organization_id),
                    "project": str(team.id),
                },
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False


def hackathon_subscription_feature(team_id: int) -> bool:
    """True when `hackathons_subscriptions` is enabled for the team's project."""
    return _team_feature_enabled(HACKATHONS_SUBSCRIPTIONS_FEATURE_FLAG_KEY, team_id)
