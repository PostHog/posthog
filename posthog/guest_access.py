"""Guest rules: what a guest may call, and the guest state of a request.

A guest is an outside member (OrganizationMembership.Level.GUEST) who may view only the objects that member
rules grant them. The rules apply only in organizations on the authz v2 rollout. See
products/authz/model/core.fga for the matching OpenFGA model.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpRequest

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.organization_caching import get_cached_organization_membership

from products.access_control.backend.facade.api import member_project_ids
from products.access_control.backend.facade.user_access_control import ACCESS_CONTROL_RESOURCES
from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType
from products.product_analytics.backend.facade.models import Insight

GUEST_MODE_FEATURE = AvailableFeature.ADVANCED_PERMISSIONS

# Object types that only the guest model covers. Guest checks on them go to OpenFGA; members keep the legacy path.
GUEST_V2_OBJECT_TYPES = frozenset({"notebook", "session_recording"})

# Project fields a guest never sees: credentials, and settings that hold tokens.
GUEST_HIDDEN_PROJECT_FIELDS = frozenset(
    {
        "secret_api_token",
        "secret_api_token_backup",
        "live_events_token",
        "heatmaps_screenshot_secret",
        "conversations_settings",
    }
)

_STATE_ATTRIBUTE = "_guest_state"
_REFERENCES_ATTRIBUTE = "_guest_references"
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


def remember_guest_state(request: Request | HttpRequest, state: GuestState) -> GuestState:
    setattr(request, _STATE_ATTRIBUTE, state)
    return state


def guest_state(request: Request | HttpRequest, organization: Organization | None) -> GuestState:
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


def guest_team_ids(user: User, organization_id: UUID) -> frozenset[int] | None:
    """Return the projects a guest may open in the organization, or None when the user is not a guest there."""
    is_guest = OrganizationMembership.objects.filter(
        user=user, organization_id=organization_id, level=OrganizationMembership.Level.GUEST
    ).exists()
    return guest_project_ids(organization_id, user) if is_guest else None


@frozen
class QueryReferences:
    cohort_ids: frozenset[int]
    action_ids: frozenset[int]


def extract_query_references(query: Any) -> QueryReferences:
    """Return the cohorts and actions that a query's structured filters name.

    Labels come only from structured filters, so HogQL text is not parsed.
    """
    cohort_ids: set[int] = set()
    action_ids: set[int] = set()
    pending = [query]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        if node.get("type") == "cohort" and isinstance(node.get("value"), int):
            cohort_ids.add(node["value"])
        if node.get("kind") == "ActionsNode" and isinstance(node.get("id"), int):
            action_ids.add(node["id"])
        if node.get("breakdown_type") == "cohort":
            breakdown = node.get("breakdown")
            values = breakdown if isinstance(breakdown, list) else [breakdown]
            cohort_ids.update(value for value in values if isinstance(value, int))
        pending.extend(node.values())
    return QueryReferences(cohort_ids=frozenset(cohort_ids), action_ids=frozenset(action_ids))


def guest_referenced_ids(request: Request, user: User, team_id: int) -> QueryReferences:
    """Return the cohorts and actions used by the insights the guest can view, once per request.

    The result is not cached across requests, so a revoked grant takes effect on the next request.
    """
    cached = getattr(request, _REFERENCES_ATTRIBUTE, None)
    if isinstance(cached, QueryReferences):
        return cached
    listed = api.list_resources(
        resource=Resource(type=ResourceType.INSIGHT, project_id=team_id),
        action=Action.VIEW,
        subject=Subject(user_id=user.pk),
    )
    cohort_ids: set[int] = set()
    action_ids: set[int] = set()
    if listed.complete:
        for query in Insight.objects.filter(team_id=team_id, id__in=listed.ids).values_list("query", flat=True):
            found = extract_query_references(query)
            cohort_ids |= found.cohort_ids
            action_ids |= found.action_ids
    references = QueryReferences(cohort_ids=frozenset(cohort_ids), action_ids=frozenset(action_ids))
    setattr(request, _REFERENCES_ATTRIBUTE, references)
    return references


def hide_project_fields_from_guest(request: Request | None, representation: dict[str, Any]) -> dict[str, Any]:
    if request is not None and is_enforced_guest(request):
        for field in GUEST_HIDDEN_PROJECT_FIELDS & representation.keys():
            representation[field] = None
    return representation


# The types a guest can be granted, with the resource type each one lists on OpenFGA.
GUEST_GRANT_TYPES = {
    "dashboard": ResourceType.DASHBOARD,
    "insight": ResourceType.INSIGHT,
    "notebook": ResourceType.NOTEBOOK,
}


def guest_effective_resource_access(user: User, team: Team) -> dict[str, str]:
    """Return the app's per-resource access for a guest: viewer for a type with a grant, none for every other type."""
    access: dict[str, str] = dict.fromkeys(ACCESS_CONTROL_RESOURCES, "none")
    for name, resource_type in GUEST_GRANT_TYPES.items():
        listed = api.list_resources(
            resource=Resource(type=resource_type, project_id=team.pk),
            action=Action.VIEW,
            subject=Subject(user_id=user.pk),
            limit=1,
        )
        # With limit=1, two or more viewable objects come back as an incomplete list, which still means access.
        if listed.ids or not listed.complete:
            access[name] = "viewer"
    return access


def _without_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_nulls(item) for item in value]
    return value


def _hogql_filters(node: Any) -> list[Any]:
    found: list[Any] = []
    pending = [node]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            if item.get("type") == "hogql":
                found.append(_without_nulls(item))
            else:
                pending.extend(item.values())
    return found


def reject_guest_value_overrides(
    request: Request | None, overrides: dict[str, Any] | None, saved: Sequence[dict[str, Any]]
) -> None:
    """Refuse a guest's filter overrides that could list values, such as emails.

    A breakdown returns every value of a property, and a HogQL filter is a yes/no test on any column. Saved filters
    stay allowed, because their author chose them. A dashboard sends its saved filters with every override, so a
    guest may repeat a saved breakdown or HogQL filter, but not send a new one.
    """
    if not overrides or request is None or not is_enforced_guest(request):
        return
    breakdown = _without_nulls(overrides.get("breakdown_filter"))
    if breakdown and breakdown not in [_without_nulls(filters.get("breakdown_filter")) for filters in saved]:
        raise PermissionDenied("Guests can't change a breakdown.")
    saved_hogql = [hogql for filters in saved for hogql in _hogql_filters(filters.get("properties"))]
    if any(hogql not in saved_hogql for hogql in _hogql_filters(overrides.get("properties"))):
        raise PermissionDenied("Guests can't filter with HogQL expressions.")
