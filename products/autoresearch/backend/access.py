"""Feature-flag gate for the autoresearch product.

Access is controlled by the `autoresearch` feature flag. Rollout is configured
on the flag in PostHog — code only asks whether it's enabled for this user/team.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

import posthoganalytics

from products.feature_flags.backend.models.feature_flag import FeatureFlag

AUTORESEARCH_FLAG = "autoresearch"


def has_autoresearch_access(user: AbstractBaseUser | AnonymousUser | None, *, team_id: int | None = None) -> bool:
    if not user or not user.is_authenticated:
        return False
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False

    # In local dev the analytics SDK is disabled; fall back to a direct ORM check.
    # Don't apply this in TEST mode — tests mock feature_enabled directly.
    if (getattr(posthoganalytics, "disabled", False) or settings.DEBUG) and not getattr(settings, "TEST", False):
        return _local_flag_enabled(team_id=team_id)

    kwargs: dict = {
        "only_evaluate_locally": False,
        "send_feature_flag_events": False,
    }
    if team_id is not None:
        kwargs["groups"] = {"project": str(team_id)}
        kwargs["group_properties"] = {"project": {"id": str(team_id)}}

    return bool(posthoganalytics.feature_enabled(AUTORESEARCH_FLAG, distinct_id, **kwargs))


def _local_flag_enabled(*, team_id: int | None) -> bool:
    qs = FeatureFlag.objects.filter(key=AUTORESEARCH_FLAG, active=True)
    if team_id is not None:
        qs = qs.filter(team_id=team_id)
    return qs.exists()
