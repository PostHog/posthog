from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from django.apps import apps
from django.db.models import Q, QuerySet

from rest_framework.permissions import SAFE_METHODS

from posthog.organization_caching import get_cached_organization

if TYPE_CHECKING:
    from posthog.models.organization import Organization


class OrganizationAccessRevocation(StrEnum):
    """Why an organization has no access.

    Declared strongest first, which is the order `organization_access_revocation` reports them in.
    A caller that gates access acts on any member of this enum. A caller that must tell the two
    apart, such as the middleware which has one screen for each, matches on the value.
    """

    PENDING_DELETION = "pending_deletion"
    DEACTIVATED = "deactivated"


class RevokedOrganizationAccess(StrEnum):
    """How much of a viewset stays reachable after an organization's access is revoked.

    A viewset that declares nothing is closed, which is what the boundary needs by default. Only
    the surfaces a revoked organization has to reach, to read why it was revoked and to pay its
    balance, declare a value here.
    """

    READS = "reads"
    # A revoked organization may read its own record and delete itself, which is how a customer
    # walks away from one, but it may not change the organization's settings while revoked.
    READS_AND_DELETE = "reads_and_delete"
    ALL = "all"


REVOCATION_MESSAGES: dict[OrganizationAccessRevocation, str] = {
    OrganizationAccessRevocation.PENDING_DELETION: "Your organization is being deleted.",
    OrganizationAccessRevocation.DEACTIVATED: "Your organization has been deactivated.",
}


# The columns `organization_access_revocation` reads. A gate that watches for a revocation change
# has to watch both of them, or a save of one column never reaches it.
REVOCATION_FIELDS = ("is_active", "is_pending_deletion")


def organization_access_revocation(organization: Organization) -> Optional[OrganizationAccessRevocation]:
    """The single read of whether an operator took an organization's access away.

    Returns None when the organization still has access. Every gate that revokes access must reach
    this function instead of reading the columns, because both columns are nullable and therefore
    hold three states. `is_active` is null on an organization that predates the column, and null
    means active, so only an explicit False revokes. A truthiness test such as
    `not organization.is_active` reads null as revoked and locks out a healthy organization.

    This function takes an organization, not an optional one, so that a caller which holds no
    organization has to decide for itself whether that is a denial. Each such decision then stays
    visible at its own call site instead of hiding behind a default answer here.
    """
    if organization.is_pending_deletion:
        return OrganizationAccessRevocation.PENDING_DELETION
    if organization.is_active is False:
        return OrganizationAccessRevocation.DEACTIVATED
    return None


def organization_access_revocation_by_id(organization_id: str | UUID) -> Optional[OrganizationAccessRevocation]:
    """`organization_access_revocation` for a caller that holds an organization id.

    The read goes through the organization access cache, which a save on the organization
    invalidates, so a revocation still lands on the next request. Prefer this over loading the
    organization through a foreign key, which costs a query on every call.

    An id that resolves to no row reports no revocation. An organization that does not exist cannot
    have its access revoked, and the caller's own lookup of that id is what has to fail.
    """
    organization = get_cached_organization(organization_id)
    return organization_access_revocation(organization) if organization is not None else None


def organization_access_revocation_message(revocation: OrganizationAccessRevocation, organization: Organization) -> str:
    """The explanation a person reads when a gate denies them.

    It mirrors the app's own revocation screens, the operator's deactivation reason included, so a
    person reads the same explanation through a token as they do in the app.
    """
    message = REVOCATION_MESSAGES[revocation]
    reason = (organization.is_not_active_reason or "").strip()
    if revocation is OrganizationAccessRevocation.DEACTIVATED and reason:
        return f"{message} {reason}"
    return message


def organization_access_revocation_for_team(team_id: int) -> Optional[OrganizationAccessRevocation]:
    """`organization_access_revocation` for a product gate that holds a team id.

    Only the team's organization id is read from the database. The revoked state itself comes from
    the organization access cache, so a gate that runs once per team in a loop pays for one
    organization read, not one per team.

    A team id that resolves to no row reports no revocation, for the same reason an unknown
    organization id does: the caller's own lookup of that team is what has to fail.
    """
    team_model = apps.get_model("posthog", "Team")
    organization_id = team_model.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return None
    return organization_access_revocation_by_id(organization_id)


# `ALL` is absent on purpose: it admits every method, so it needs no list of them.
REACHABLE_METHODS: dict[RevokedOrganizationAccess, frozenset[str]] = {
    RevokedOrganizationAccess.READS: frozenset(SAFE_METHODS),
    RevokedOrganizationAccess.READS_AND_DELETE: frozenset(SAFE_METHODS) | {"DELETE"},
}


def exclude_revoked_organizations(queryset: QuerySet, path: str = "organization") -> QuerySet:
    """Drop the rows whose organization had its access revoked.

    The queryset twin of `organization_access_revocation`, for a list. DRF runs no object
    permission over list rows, so a list filters where a detail read denies. Filtering is also what
    someone who belongs to both a revoked and a healthy organization needs: denying the whole list
    would take the healthy organization's rows with it.

    Null means active in both columns, exactly as the scalar check reads them, so a row whose
    organization predates either column stays visible. `test_the_queryset_filter_agrees_with_the
    _scalar_check` pins the two together.
    """
    active = Q(**{f"{path}__is_active": True}) | Q(**{f"{path}__is_active__isnull": True})
    not_deleting = Q(**{f"{path}__is_pending_deletion": False}) | Q(**{f"{path}__is_pending_deletion__isnull": True})
    return queryset.filter(active & not_deleting)
