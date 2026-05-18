"""Feature-flag gate for the Deployments product.

Access is gated on the `deployments` feature flag. Rollout (e.g. limiting to
specific teams or organizations) is configured on the flag itself in the
PostHog admin — code only asks 'is this enabled for this user / team?' and
returns the answer.
"""

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

import posthoganalytics


def has_deployments_access(user: AbstractBaseUser | AnonymousUser | None, *, team_id: int | None = None) -> bool:
    # Accept the union DRF gives us on `request.user` (authenticated User or AnonymousUser).
    # Bail on anything that can't carry a distinct_id — the flag check below needs one.
    if not user or not user.is_authenticated:
        return False
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False

    kwargs: dict = {
        "only_evaluate_locally": False,
        "send_feature_flag_events": False,
    }
    if team_id is not None:
        kwargs["groups"] = {"project": str(team_id)}
        kwargs["group_properties"] = {"project": {"id": str(team_id)}}

    return bool(posthoganalytics.feature_enabled("deployments", distinct_id, **kwargs))
