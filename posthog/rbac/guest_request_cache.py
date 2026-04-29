"""Request-scoped cache for the user's guest membership state.

`GuestDeflectionMiddleware` runs once on every authenticated request and asks
"is this user a guest in any org?". Several downstream code paths
(`UserSerializer.get_is_guest_in_current_project`, `UserSerializer.get_guest_grants`,
`filter_and_sanitize_teams_for_guest_access`) ask the same question again, scoped
to a specific org. Without coordination, each consumer issues its own DB lookup
on the same hot path — costing 4+ extra queries on `/api/users/@me/`.

This module exposes one helper, `get_user_guest_org_ids`, that resolves the
union of org-ids the user is a guest in *once per request* and stashes the
result on the `HttpRequest`. All consumers should go through this helper rather
than querying `OrganizationMembership` directly when they only need the boolean
answer "is this user a guest in org X?".

For consumers that need the `OrganizationMembership` object itself (e.g. to
read `bypass_sso` or grant rows), `get_user_guest_membership` returns the
cached membership, fetching it lazily on first request and storing it under
`request._guest_membership_by_org`.
"""

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from django.http import HttpRequest

if TYPE_CHECKING:
    from posthog.models import OrganizationMembership


_GUEST_ORG_IDS_ATTR = "_guest_org_ids"
_GUEST_MEMBERSHIP_ATTR = "_guest_membership_by_org"


def get_user_guest_org_ids(request: HttpRequest) -> frozenset[UUID]:
    """Return the set of org-ids the requesting user is a guest in.

    Empty frozenset for anonymous users, unauthenticated requests, or users
    with no guest memberships. Cached on the request — subsequent calls within
    the same request lifecycle return the cached set without another DB hit.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()

    cached = getattr(request, _GUEST_ORG_IDS_ATTR, None)
    if cached is not None:
        return cached

    org_ids = frozenset(user.organization_memberships.filter(is_guest=True).values_list("organization_id", flat=True))
    setattr(request, _GUEST_ORG_IDS_ATTR, org_ids)
    return org_ids


def is_user_guest_in_any_org(request: HttpRequest) -> bool:
    """Convenience wrapper for the middleware's "deflect if guest" check."""
    return bool(get_user_guest_org_ids(request))


def is_user_guest_in_org(request: HttpRequest, organization_id: UUID | str) -> bool:
    """Return True if the requesting user is a guest in the given org."""
    if isinstance(organization_id, str):
        organization_id = UUID(organization_id)
    return organization_id in get_user_guest_org_ids(request)


def get_user_guest_membership(request: HttpRequest, organization_id: UUID | str) -> Optional["OrganizationMembership"]:
    """Return the user's `OrganizationMembership` for `organization_id` if they
    are a guest there, else None.

    The membership row is loaded lazily on first request and cached on
    `request._guest_membership_by_org`. Non-guest membership lookups should
    continue to use the standard ORM path.
    """
    from posthog.models import OrganizationMembership

    if isinstance(organization_id, str):
        organization_id = UUID(organization_id)
    if organization_id not in get_user_guest_org_ids(request):
        return None

    cache: dict[UUID, OrganizationMembership] = getattr(request, _GUEST_MEMBERSHIP_ATTR, None) or {}
    if organization_id in cache:
        return cache[organization_id]

    membership = OrganizationMembership.objects.filter(
        user=request.user,
        organization_id=organization_id,
        is_guest=True,
    ).first()
    if membership is not None:
        cache[organization_id] = membership
        setattr(request, _GUEST_MEMBERSHIP_ATTR, cache)
    return membership
