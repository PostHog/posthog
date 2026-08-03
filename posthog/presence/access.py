"""
Per-scope authorization for presence.

Presence answers "who is looking at this object", which leaks both the object's existence and who
is interested in it, so team membership alone is not enough — a support ticket, for instance, is
only readable to agents with object-level access to it. Rather than a growing `if/elif` in the API
layer, each product registers a check for the scopes it owns and core stays decoupled from
products. Unregistered scopes are denied, so presence is strictly opt-in.
"""

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING

from django.core import exceptions as django_exceptions
from django.db.models import Model

from rest_framework import exceptions

if TYPE_CHECKING:
    from posthog.models import User
    from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl


@dataclasses.dataclass(frozen=True, kw_only=True)
class PresenceAccessContext:
    team_id: int
    scope: str
    item_id: str
    user: "User"
    user_access_control: "UserAccessControl"


PresenceAccessCheck = Callable[[PresenceAccessContext], None]

_REGISTRY: dict[str, PresenceAccessCheck] = {}


def register_presence_scope(scope: str, check: PresenceAccessCheck) -> None:
    """Enable presence for `scope`. Call from an AppConfig.ready() so it runs exactly once."""
    _REGISTRY[scope] = check


def check_presence_access(context: PresenceAccessContext) -> None:
    """Raise unless the caller may see presence for this scope and item."""
    check = _REGISTRY.get(context.scope)
    if check is None:
        # 404 rather than 403: an unregistered scope shouldn't be distinguishable from a scope that
        # exists but is empty, or presence becomes an existence oracle for arbitrary ids.
        raise exceptions.NotFound("Presence is not available for this scope")
    check(context)


def model_access_check(
    model_getter: Callable[[int, str], Model | None],
    *,
    required_level: "AccessControlLevel" = "viewer",
) -> PresenceAccessCheck:
    """Check for the common case: the scope is a team-scoped model with object-level RBAC."""

    def check(context: PresenceAccessContext) -> None:
        try:
            instance = model_getter(context.team_id, context.item_id)
        except (ValueError, TypeError, django_exceptions.ValidationError):
            # A malformed item_id (e.g. not a UUID) is indistinguishable from a missing object.
            instance = None

        if instance is None:
            raise exceptions.NotFound("Not found")

        if not context.user_access_control.check_access_level_for_object(instance, required_level=required_level):
            raise exceptions.PermissionDenied("You do not have access to this object")

    return check
