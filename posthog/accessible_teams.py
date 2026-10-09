from collections.abc import Sequence
from dataclasses import field
from typing import Self, cast

from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.permissions import get_authenticator_scoped_team_ids
from posthog.user_permissions import UserPermissions

_CONSTRUCTION_TOKEN = object()


class CredentialScopeDenied(Exception):
    pass


@frozen
class AccessibleTeams:
    """The teams one user may scope a credential to.

    Only the classmethods build an instance, and each runs the project access check first, so code
    that receives an instance knows the check ran for `user_id`. Direct construction raises.
    """

    user_id: int
    # None means no team restriction: the request-time permission checks decide which teams the
    # credential reaches each time it is used.
    team_ids: tuple[int, ...] | None
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _CONSTRUCTION_TOKEN:
            raise TypeError("Build AccessibleTeams with for_user, for_request or all_for.")

    @classmethod
    def for_user(cls, user: User, team_ids: Sequence[int]) -> Self:
        requested = tuple(dict.fromkeys(team_ids))
        if not requested:
            raise ValueError("Pass at least one team id, or use all_for for no team restriction.")

        teams = list(Team.objects.filter(pk__in=requested))
        if len(teams) != len(requested):
            raise CredentialScopeDenied("One or more teams do not exist.")

        user_permissions = UserPermissions(user)
        if any(user_permissions.team(team).effective_membership_level is None for team in teams):
            raise CredentialScopeDenied("The user cannot access one or more teams.")

        return cls(user_id=user.pk, team_ids=requested, _token=_CONSTRUCTION_TOKEN)

    @classmethod
    def for_request(cls, request: Request, team_ids: Sequence[int] | None) -> Self:
        """Like `for_user`, but also confined to the teams that the request's credential reaches.

        `None` asks for no team restriction. Only a credential without a team restriction can
        grant that, because a key confined to some teams must not hand out a wider one.
        """
        user = cast(User, request.user)
        credential_team_ids = get_authenticator_scoped_team_ids(getattr(request, "successful_authenticator", None))

        if team_ids is None:
            if credential_team_ids is not None:
                raise CredentialScopeDenied("A credential confined to some teams cannot grant all of them.")
            return cls.all_for(user)

        if credential_team_ids is not None and not set(team_ids) <= set(credential_team_ids):
            raise CredentialScopeDenied("The credential does not reach one or more teams.")

        return cls.for_user(user, team_ids)

    @classmethod
    def all_for(cls, user: User) -> Self:
        return cls(user_id=user.pk, team_ids=None, _token=_CONSTRUCTION_TOKEN)
