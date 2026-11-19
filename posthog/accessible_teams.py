from collections.abc import Sequence
from dataclasses import field
from typing import Self, cast

from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.ip_restrictions import enforce_ip_restrictions, get_ip_blocked_organization_ids
from posthog.models import Team, User
from posthog.permissions import get_authenticator_scoped_organization_ids, get_authenticator_scoped_team_ids

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import CheckRequest, Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType

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

        subject = Subject(user_id=user.pk)
        allowed = authorization.check(
            [
                CheckRequest(
                    resource=Resource(type=ResourceType.PROJECT, id=str(team.pk)), action=Action.VIEW, subject=subject
                )
                for team in teams
            ]
        )
        if not all(allowed):
            raise CredentialScopeDenied("The user cannot access one or more teams.")

        return cls(user_id=user.pk, team_ids=requested, _token=_CONSTRUCTION_TOKEN)

    @classmethod
    def for_request(cls, request: Request, team_ids: Sequence[int] | None) -> Self:
        """Like `for_user`, but also enforces the request credential and owning organizations' IP policies.

        `None` asks for no team restriction. Only a credential without an organization or team
        restriction can grant that, because a key confined to some orgs or teams must not hand
        out a wider one.
        """
        user = cast(User, request.user)
        authenticator = getattr(request, "successful_authenticator", None)
        credential_team_ids = get_authenticator_scoped_team_ids(authenticator)
        credential_organization_ids = get_authenticator_scoped_organization_ids(authenticator)

        if team_ids is None:
            if credential_team_ids is not None or credential_organization_ids is not None:
                raise CredentialScopeDenied("A credential confined to some orgs or teams cannot grant all of them.")
            return cls.all_for(user)

        if credential_team_ids is not None and not set(team_ids) <= set(credential_team_ids):
            raise CredentialScopeDenied("The credential does not reach one or more teams.")

        if credential_organization_ids is not None:
            allowed_organization_ids = {str(org_id) for org_id in credential_organization_ids}
            requested_organization_ids = {
                str(org_id) for org_id in Team.objects.filter(pk__in=team_ids).values_list("organization_id", flat=True)
            }
            if not requested_organization_ids or not requested_organization_ids <= allowed_organization_ids:
                raise CredentialScopeDenied("The credential does not reach one or more organizations.")

        accessible = cls.for_user(user, team_ids)
        blocked_organizations = get_ip_blocked_organization_ids(request)
        if blocked_organizations:
            blocked_organization = (
                Team.objects.filter(pk__in=team_ids, organization_id__in=blocked_organizations)
                .values_list("organization_id", flat=True)
                .first()
            )
            if blocked_organization is not None:
                enforce_ip_restrictions(request, user, authenticator, organization_id=str(blocked_organization))
        return accessible

    @classmethod
    def all_for(cls, user: User) -> Self:
        return cls(user_id=user.pk, team_ids=None, _token=_CONSTRUCTION_TOKEN)
