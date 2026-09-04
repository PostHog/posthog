"""Feature-flag gate for the autoresearch product.

Access is controlled by the `autoresearch` feature flag. Rollout is configured
on the flag in PostHog, so code only asks whether it's enabled for this user/team.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

import posthoganalytics

from posthog.models.team import Team
from posthog.permissions import posthog_feature_flag_value

from products.feature_flags.backend.facade import api as feature_flags_facade

AUTORESEARCH_FLAG = "autoresearch"


def has_autoresearch_access(
    user: AbstractBaseUser | AnonymousUser | None,
    *,
    team_id: int | None = None,
    organization_id: str | None = None,
) -> bool:
    if not user or not user.is_authenticated:
        return False
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False

    # In local dev the analytics SDK is disabled; fall back to a direct ORM check.
    # DEBUG only: a production instance that disables the SDK (OPT_OUT_CAPTURE) must
    # fail closed rather than grant access on any active flag row.
    # Don't apply this in TEST mode, because tests mock feature_enabled directly.
    if settings.DEBUG and not getattr(settings, "TEST", False):
        return _local_flag_enabled(team_id=team_id)

    if team_id is not None and organization_id is None:
        organization_id = _organization_id_for_team(team_id)

    # An organization-targeted rollout reaches the in-app flag evaluation, which sends the
    # organization group. The shared helper sends it too, or the product renders and every
    # request 403s. It also honors POSTHOG_FEATURE_FLAGS_FORCE_ENABLED, which a direct SDK
    # call would skip.
    if organization_id is not None:
        return bool(
            posthog_feature_flag_value(
                AUTORESEARCH_FLAG,
                distinct_id,
                organization_id=organization_id,
                team_id=team_id,
            )
        )

    # No resolvable organization: evaluate with whatever group context exists.
    groups: dict[str, str] = {}
    group_properties: dict[str, dict[str, str]] = {}
    if team_id is not None:
        groups["project"] = str(team_id)
        group_properties["project"] = {"id": str(team_id)}

    return bool(
        posthoganalytics.feature_enabled(
            AUTORESEARCH_FLAG,
            distinct_id,
            groups=groups,
            group_properties=group_properties,
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def _organization_id_for_team(team_id: int) -> str | None:
    organization_id = Team.objects.filter(pk=team_id).values_list("organization_id", flat=True).first()
    return str(organization_id) if organization_id else None


def _local_flag_enabled(*, team_id: int | None) -> bool:
    return feature_flags_facade.flag_is_active(AUTORESEARCH_FLAG, team_id=team_id)
