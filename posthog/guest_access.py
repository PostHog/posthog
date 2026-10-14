"""Guest rules: what a guest may call, and the guest state of a request.

A guest is an outside member (OrganizationMembership.Level.GUEST) who may view only the objects that member
rules grant them. The rules apply only in organizations on the authz v2 rollout. See
products/authz/model/core.fga for the matching OpenFGA model.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models import Organization, OrganizationMembership, User
from posthog.organization_caching import get_cached_organization_membership

from products.access_control.backend.facade.api import member_project_ids
from products.authz.backend.facade import api

GUEST_MODE_FEATURE = AvailableFeature.ADVANCED_PERMISSIONS

# A user view only reads and changes the request user's own account, so a guest may call all of it.
GUEST_ANY_ACTION_SCOPES = frozenset({"user"})

# A guest may call only these actions. AccessControlPermission or the view checks each object again.
GUEST_ALLOWED: Mapping[str, frozenset[str]] = {
    "organization": frozenset({"retrieve"}),
    "project": frozenset({"retrieve"}),
    "dashboard": frozenset({"list", "retrieve", "stream_tiles"}),
    "insight": frozenset({"list", "retrieve"}),
    "notebook": frozenset({"list", "retrieve"}),
    "session_recording": frozenset({"retrieve", "snapshots", "snapshot_file"}),
    "query": frozenset({"create", "create_with_kind", "retrieve", "destroy"}),
    "event_definition": frozenset({"list", "retrieve"}),
    "property_definition": frozenset({"list", "retrieve"}),
    "cohort": frozenset({"list", "retrieve"}),
    "action": frozenset({"list", "retrieve"}),
    "annotation": frozenset({"list", "retrieve"}),
}

# Object types that only the guest model covers. Guest checks on them go to OpenFGA; members keep the legacy path.
GUEST_V2_OBJECT_TYPES = frozenset({"notebook", "session_recording"})

_STATE_ATTRIBUTE = "_guest_state"
_LOOKUP_ERRORS = (AttributeError, KeyError, ValueError, NotFound, Http404, ObjectDoesNotExist, PermissionDenied)


@frozen
class GuestState:
    is_guest: bool
    organization: Organization | None
    # True when the organization is on authz v2, so the guest rules apply. Otherwise a guest acts as a member.
    enforced: bool


NOT_A_GUEST = GuestState(is_guest=False, organization=None, enforced=False)


def build_guest_state(membership: OrganizationMembership | None) -> GuestState:
    if membership is None or membership.level != OrganizationMembership.Level.GUEST:
        return NOT_A_GUEST
    organization = membership.organization
    return GuestState(is_guest=True, organization=organization, enforced=api.guest_mode_active(organization.id))


def remember_guest_state(request: Request, state: GuestState) -> GuestState:
    setattr(request, _STATE_ATTRIBUTE, state)
    return state


def guest_state(request: Request, organization: Organization | None) -> GuestState:
    """Return the guest state for a caller outside the permission stack, such as the app context."""
    cached = getattr(request, _STATE_ATTRIBUTE, None)
    if isinstance(cached, GuestState):
        return cached
    user = request.user
    membership = (
        get_cached_organization_membership(organization.id, user)
        if organization is not None and isinstance(user, User)
        else None
    )
    return remember_guest_state(request, build_guest_state(membership))


def guest_state_for_view(request: Request, view: Any) -> GuestState:
    """Return the guest state of a request to a view, and cache it on the request."""
    cached = getattr(request, _STATE_ATTRIBUTE, None)
    if isinstance(cached, GuestState):
        return cached
    user = request.user
    if not isinstance(user, User):
        return remember_guest_state(request, NOT_A_GUEST)
    return remember_guest_state(request, build_guest_state(_view_membership(view, user)))


def _view_membership(view: Any, user: User) -> OrganizationMembership | None:
    # A team view loads every membership of the user once, and TeamMemberAccessPermission reads the same
    # cached dict, so this adds no query there. Other views use the organization access cache.
    try:
        return view.user_permissions.organization_memberships.get(UUID(str(view.organization_id)))
    except _LOOKUP_ERRORS:
        pass
    organization_id: UUID | None = None
    for lookup in (lambda: view.organization.id, lambda: view.team.organization_id):
        try:
            organization_id = lookup()
            break
        except _LOOKUP_ERRORS:
            continue
    organization_id = organization_id or user.current_organization_id
    return get_cached_organization_membership(organization_id, user) if organization_id is not None else None


def is_enforced_guest(request: Request) -> bool:
    state = getattr(request, _STATE_ATTRIBUTE, None)
    return isinstance(state, GuestState) and state.enforced


def guest_project_ids(organization_id: UUID, user: User) -> frozenset[int]:
    return member_project_ids(organization_id=organization_id, user_id=user.pk)
