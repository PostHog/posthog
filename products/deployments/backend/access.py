"""Feature-flag gate for the Deployments product.

Access is gated on the `deployments` feature flag. Rollout (e.g. limiting to
specific teams or organizations) is configured on the flag itself in the
PostHog admin — code only asks 'is this enabled for this user / team?' and
returns the answer.
"""

import posthoganalytics

from posthog.models.user import User


def has_deployments_access(user: User, *, team_id: int | None = None) -> bool:
    if not user or not user.is_authenticated or not user.distinct_id:
        return False

    kwargs: dict = {
        "only_evaluate_locally": False,
        "send_feature_flag_events": False,
    }
    if team_id is not None:
        kwargs["groups"] = {"project": str(team_id)}
        kwargs["group_properties"] = {"project": {"id": str(team_id)}}

    return bool(posthoganalytics.feature_enabled("deployments", user.distinct_id, **kwargs))
