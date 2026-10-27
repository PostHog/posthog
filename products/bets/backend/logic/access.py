from django.conf import settings

import posthoganalytics
from rest_framework.exceptions import PermissionDenied

from posthog.models import Team, User

from ..adapters.identity import PostHogIdentity
from ..facade.enums import BetsAccessLevel


def bets_enabled(team: Team) -> bool:
    if settings.DEBUG and not settings.TEST:
        return True
    return bool(
        posthoganalytics.feature_enabled(
            "bets",
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            send_feature_flag_events=False,
        )
    )


def require(team: Team, user: User, *, write: bool = False) -> None:
    level = PostHogIdentity().access_level(user, team)
    if level is None or (write and level not in (BetsAccessLevel.TRADER, BetsAccessLevel.MANAGER)):
        raise PermissionDenied(
            "You do not have permission to change bets." if write else "You do not have access to bets."
        )


def require_manager(team: Team, user: User) -> None:
    if PostHogIdentity().access_level(user, team) != BetsAccessLevel.MANAGER:
        raise PermissionDenied("Only a project admin can change Bets settings.")


def require_owner(team: Team, user: User, owner_id: int) -> None:
    require(team, user, write=True)
    if user.id != owner_id and PostHogIdentity().access_level(user, team) != BetsAccessLevel.MANAGER:
        raise PermissionDenied("Only the owner of this bet can change it. You can back it with more budget.")
