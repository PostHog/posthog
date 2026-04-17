from typing import Any

from django.db import transaction
from django.db.models import QuerySet

from rest_framework import exceptions

from posthog.constants import AvailableFeature
from posthog.models import GuestResourceGrant, OrganizationMembership
from posthog.models.organization import Organization
from posthog.models.user import User


def require_admin(*, organization: Organization, user: User) -> OrganizationMembership:
    """Resolve the requesting user's membership and assert admin-or-above level.
    Raises PermissionDenied if the user is not an admin/owner.
    """
    try:
        membership = OrganizationMembership.objects.get(organization=organization, user=user)
    except OrganizationMembership.DoesNotExist:
        raise exceptions.PermissionDenied("You must be a member of this organization.")
    if membership.level < OrganizationMembership.Level.ADMIN:
        raise exceptions.PermissionDenied("Only org admins and owners can perform this action.")
    return membership


def promote_guest_to_member(*, membership: OrganizationMembership, promoted_by: User) -> int:
    """Flip a guest to a regular member and delete all grants. Returns grants removed count.
    Raises ValidationError if the membership is not a guest.
    Raises PermissionDenied if the caller is not admin/owner.
    """
    require_admin(organization=membership.organization, user=promoted_by)

    if not membership.is_guest:
        raise exceptions.ValidationError("User is already a regular member of this organization.")

    with transaction.atomic():
        grants_removed = GuestResourceGrant.objects.filter(organization_membership=membership).count()
        GuestResourceGrant.objects.filter(organization_membership=membership).delete()
        membership.is_guest = False
        membership.bypass_sso_enforcement = False
        membership.save()

    return grants_removed


def list_grants(*, membership: OrganizationMembership) -> QuerySet[GuestResourceGrant]:
    """Active + pending grants for a membership."""
    return GuestResourceGrant.objects.filter(organization_membership=membership)


def add_grant(
    *,
    membership: OrganizationMembership,
    team_id: int,
    resource: str,
    resource_id: int,
    created_by: User,
) -> GuestResourceGrant:
    """Create an active grant on a guest membership.
    Raises ValidationError if the target is not a guest or the resource type is invalid.
    """
    if not membership.is_guest:
        raise exceptions.ValidationError("Cannot create grants on a non-guest membership.")
    if resource not in {"dashboard", "insight", "notebook"}:
        raise exceptions.ValidationError(f"Invalid resource: {resource}")
    return GuestResourceGrant.objects.create(
        organization_membership=membership,
        team_id=team_id,
        resource=resource,
        resource_id=resource_id,
        is_pending=False,
        created_by=created_by,
    )


def remove_grant(*, grant: GuestResourceGrant) -> None:
    """Delete a single grant."""
    grant.delete()


def validate_guest_invite(
    *,
    organization: Organization,
    target_email: str,
    grants: list[dict[str, Any]],
    bypass_sso_enforcement: bool,
    bypass_acknowledged: bool,
) -> None:
    """Validate all guest-invite preconditions. Raises ValidationError on failure.
    Called from the invite serializer's validate() method.
    """
    if not organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        raise exceptions.ValidationError("Guest invites require the Access Control feature. Please upgrade your plan.")

    if not grants:
        raise exceptions.ValidationError("Guest invites must specify at least one resource grant.")

    if bypass_sso_enforcement and not bypass_acknowledged:
        raise exceptions.ValidationError(
            "You must set bypass_acknowledged=True to confirm you understand the SSO bypass implications."
        )

    if (
        target_email
        and OrganizationMembership.objects.filter(
            organization=organization, user__email__iexact=target_email, is_guest=False
        ).exists()
    ):
        raise exceptions.ValidationError(
            "This email address belongs to an existing regular member. Regular members cannot be invited as guests."
        )

    _validate_grant_shapes(organization=organization, grants=grants)


def _validate_grant_shapes(*, organization: Organization, grants: list[dict[str, Any]]) -> None:
    org_team_ids = set(organization.teams.values_list("id", flat=True))
    valid_resources = {"dashboard", "insight", "notebook"}

    from posthog.models.insight import Insight

    from products.dashboards.backend.models.dashboard import Dashboard
    from products.notebooks.backend.models import Notebook

    resource_model_map: dict[str, Any] = {
        "dashboard": Dashboard,
        "insight": Insight,
        "notebook": Notebook,
    }

    for grant in grants:
        team_id = grant.get("team_id")
        resource = grant.get("resource")
        resource_id = grant.get("resource_id")

        if team_id not in org_team_ids:
            raise exceptions.ValidationError(f"Team {team_id} does not belong to this organization.")
        if resource not in valid_resources:
            raise exceptions.ValidationError(
                f"Invalid resource type '{resource}'. Must be one of: {', '.join(sorted(valid_resources))}."
            )
        model = resource_model_map[resource]
        if not model.objects.filter(id=resource_id, team_id=team_id).exists():
            raise exceptions.ValidationError(f"{resource.capitalize()} {resource_id} does not exist in team {team_id}.")


def create_pending_grants(*, invite, grants: list[dict[str, Any]], created_by: User) -> list[GuestResourceGrant]:
    """Create pending GuestResourceGrant rows attached to an invite."""
    created = []
    for grant in grants:
        created.append(
            GuestResourceGrant.objects.create(
                invite=invite,
                team_id=grant["team_id"],
                resource=grant["resource"],
                resource_id=grant["resource_id"],
                is_pending=True,
                created_by=created_by,
            )
        )
    return created


def accept_guest_invite(*, invite, user: User) -> OrganizationMembership:
    """Create a guest membership from an accepted invite and activate all pending grants.
    Called from OrganizationInvite.use() when is_guest=True.
    """
    membership = OrganizationMembership.objects.create(
        organization=invite.organization,
        user=user,
        level=OrganizationMembership.Level.MEMBER,
        is_guest=True,
        bypass_sso_enforcement=invite.bypass_sso_enforcement,
    )
    for grant in GuestResourceGrant.objects.filter(invite=invite):
        grant.organization_membership = membership
        grant.invite = None
        grant.is_pending = False
        grant.save()
    return membership


def guest_access_level_for_object(
    *,
    org_membership: OrganizationMembership,
    team,
    resource: str,
    obj_id: int,
) -> str | None:
    """Return the access level a guest has for a specific object.
    Returns "viewer" if the guest has a direct grant or the object is a tile of a granted dashboard.
    Returns None otherwise.
    """
    direct = GuestResourceGrant.objects.filter(
        organization_membership=org_membership,
        team=team,
        resource=resource,
        resource_id=obj_id,
        is_pending=False,
    ).exists()
    if direct:
        return "viewer"

    if resource == "insight":
        from products.dashboards.backend.models.dashboard_tile import DashboardTile

        dashboard_ids = DashboardTile.objects.filter(insight_id=obj_id).values_list("dashboard_id", flat=True)
        if (
            dashboard_ids
            and GuestResourceGrant.objects.filter(
                organization_membership=org_membership,
                team=team,
                resource="dashboard",
                resource_id__in=list(dashboard_ids),
                is_pending=False,
            ).exists()
        ):
            return "viewer"

    return None


def is_guest_sso_bypass_allowed(*, email: str) -> bool:
    """Check if any guest membership for this email has bypass_sso_enforcement=True
    in an org whose verified domain enforces SSO.
    Called from the login flow when SSO enforcement would otherwise block password auth.
    """
    from posthog.models.organization_domain import OrganizationDomain

    domain = email[email.index("@") + 1 :]
    enforcing_org_ids = list(
        OrganizationDomain.objects.verified_domains()
        .filter(domain__iexact=domain)
        .exclude(sso_enforcement="")
        .values_list("organization_id", flat=True)
    )
    if not enforcing_org_ids:
        return False
    return OrganizationMembership.objects.filter(
        organization_id__in=enforcing_org_ids,
        user__email__iexact=email,
        is_guest=True,
        bypass_sso_enforcement=True,
    ).exists()
