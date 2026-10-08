from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.http import HttpRequest

from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.helpers.impersonation import is_impersonated

if TYPE_CHECKING:
    from posthog.models.team import Team


@frozen
class ActivityActor:
    """Who made a change, for its activity log row.

    It holds plain ids, so a product facade can pass it across its boundary without a `User` row.
    """

    organization_id: UUID
    team_id: int
    user_id: int | None
    was_impersonated: bool

    @classmethod
    def from_request(cls, request: HttpRequest | Request, team: Team) -> ActivityActor:
        # The row belongs to the team's organization. The user's current organization can be a different one.
        user = request.user
        return cls(
            organization_id=team.organization_id,
            team_id=team.id,
            user_id=user.pk if user.is_authenticated else None,
            was_impersonated=is_impersonated(request),
        )

    @classmethod
    def system(cls, team: Team) -> ActivityActor:
        return cls(organization_id=team.organization_id, team_id=team.id, user_id=None, was_impersonated=False)
