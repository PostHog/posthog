"""Guest grants service.

A guest's access is expressed as `AccessControl` rows scoped to their OrganizationMembership.
The inversion in `UserAccessControl` flips the default for guests from "allow" to "deny", so
an AC row is both necessary and sufficient: this module is a thin wrapper around AC writes
plus the notebook embedded-node cascade (centralized in `notebook_cascade.py`).

Scope: notebook only. Dashboard and insight grants land in a follow-up PR.

Adding a new resource type means accepting it in `VALID_RESOURCES` and ensuring the
`_ac_resource_id` translation matches how the URL-side identifier differs from the AC PK.
"""

from typing import Any

from django.db import transaction

from rest_framework import exceptions

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.notebooks.backend.models import Notebook

from ee.models.rbac.access_control import AccessControl

VALID_RESOURCES: tuple[str, ...] = ("notebook",)
VALID_GUEST_ACCESS_LEVELS: tuple[str, ...] = ("viewer", "editor")
GUEST_VIEWER_ACCESS_LEVEL = "viewer"


def _resource_exists_in_team(resource: str, resource_id: str, team_id: int) -> bool:
    """Does the grant target actually exist? Notebook URL identifiers are `short_id`, but
    legacy numeric PK addressing is also allowed."""
    value = str(resource_id)
    if resource != "notebook":
        return False
    if value.isdigit() and Notebook.objects.filter(id=int(value), team_id=team_id).exists():
        return True
    return Notebook.objects.filter(short_id=value, team_id=team_id).exists()


def validate_invite_grants(organization: Organization, guest_resources: list[dict[str, Any]]) -> None:
    """Validate the shape and existence of each entry in an invite's `guest_resources`.

    The structural validation of `access_level` is handled by the field-level validator on
    `OrganizationInvite.guest_resources` (see `posthog/models/organization_invite.py`) — this
    service-level validator only checks team membership and resource existence.
    """
    if not organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        raise exceptions.ValidationError(
            "Guest invites require the Advanced permissions feature. Upgrade to enable them."
        )

    if not guest_resources:
        raise exceptions.ValidationError("Guest invites must specify at least one resource grant.")

    org_team_ids = set(organization.teams.values_list("id", flat=True))

    for grant in guest_resources:
        team_id = grant.get("team_id")
        resource = grant.get("resource")
        resource_id = grant.get("resource_id")

        if team_id not in org_team_ids:
            raise exceptions.ValidationError(f"Team {team_id} does not belong to this organization.")
        if resource not in VALID_RESOURCES:
            raise exceptions.ValidationError(
                f"Invalid resource type '{resource}'. Must be one of: {', '.join(sorted(VALID_RESOURCES))}."
            )
        if resource_id is None or not _resource_exists_in_team(resource, str(resource_id), int(team_id)):
            raise exceptions.ValidationError(f"{resource.capitalize()} {resource_id} does not exist in team {team_id}.")


@transaction.atomic
def create_grant(
    *,
    membership: OrganizationMembership,
    team: Team,
    resource: str,
    resource_id: str,
    created_by: User,
    access_level: str = GUEST_VIEWER_ACCESS_LEVEL,
) -> AccessControl:
    """Write a single `AccessControl` row for this guest membership."""
    if resource not in VALID_RESOURCES:
        raise exceptions.ValidationError(f"Invalid resource: {resource}")
    if access_level not in VALID_GUEST_ACCESS_LEVELS:
        raise exceptions.ValidationError(
            f"Invalid access level '{access_level}'. Must be one of: {', '.join(VALID_GUEST_ACCESS_LEVELS)}."
        )

    ac_resource_id = _ac_resource_id(resource, str(resource_id), team.id)
    if ac_resource_id is None:
        raise exceptions.ValidationError(f"{resource.capitalize()} {resource_id} does not exist in team {team.id}.")

    access_control, _ = AccessControl.objects.get_or_create(
        team=team,
        resource=resource,
        resource_id=ac_resource_id,
        organization_member=membership,
        role=None,
        defaults={"access_level": access_level, "created_by": created_by},
    )
    # Keep the level up-to-date if a grant for this resource already existed (e.g. an admin
    # re-runs the same invite with a higher level). `get_or_create` above short-circuits in
    # that case, so bump the level defensively.
    if access_control.access_level != access_level:
        access_control.access_level = access_level
        access_control.save(update_fields=["access_level", "updated_at"])

    if resource == "notebook":
        # Cascade AC rows to every cascadeable embedded resource referenced in the notebook
        # content (saved insights, recordings, cohorts, feature flags, etc.) at viewer level.
        # The embed map is centralized in `posthog/rbac/notebook_cascade.py`.
        from posthog.rbac.notebook_cascade import cascade_grants_for_notebook

        notebook = Notebook.objects.filter(id=ac_resource_id, team_id=team.id).first()
        if notebook is not None:
            cascade_grants_for_notebook(
                notebook=notebook,
                membership=membership,
                team=team,
                created_by=created_by,
            )

    return access_control


def _ac_resource_id(resource: str, grant_resource_id: str, team_id: int) -> str | None:
    """Guest grants accept URL identifiers (short_id for notebooks), while the AC table
    uses the numeric PK. Translate before writing AC rows."""
    if resource != "notebook":
        return None
    if grant_resource_id.isdigit():
        return grant_resource_id
    pk = Notebook.objects.filter(short_id=grant_resource_id, team_id=team_id).values_list("id", flat=True).first()
    return str(pk) if pk is not None else None


@transaction.atomic
def revoke_grants_for_membership(membership: OrganizationMembership) -> int:
    """Delete every AC row tied to this guest membership. Returns the number of rows removed."""
    deleted, _ = AccessControl.objects.filter(organization_member=membership).delete()
    return int(deleted)


@transaction.atomic
def apply_invite_grants(
    invite: "Any",  # OrganizationInvite — annotated as Any to avoid a circular import
    new_membership: OrganizationMembership,
) -> list[AccessControl]:
    """Materialize an invite's `guest_resources` into AccessControl rows on the new membership."""
    created: list[AccessControl] = []
    for entry in invite.guest_resources or []:
        team = Team.objects.get(id=entry["team_id"])
        access_level = entry.get("access_level", GUEST_VIEWER_ACCESS_LEVEL)
        created.append(
            create_grant(
                membership=new_membership,
                team=team,
                resource=entry["resource"],
                resource_id=str(entry["resource_id"]),
                created_by=invite.created_by,
                access_level=access_level,
            )
        )
    return created


@transaction.atomic
def promote_to_member(membership: OrganizationMembership, by: User) -> int:
    """Convert a guest membership into a regular member.

    Deletes all AC rows owned by this membership and flips `is_guest` (and the SSO carve-out)
    off. Returns the number of AC rows removed so the API response can surface it.
    """
    if not membership.is_guest:
        raise exceptions.ValidationError("This membership is already a regular member.")

    removed = revoke_grants_for_membership(membership)

    # Reset SSO bypass on promotion — the carve-out was granted for a guest scenario;
    # elevating to full member should require re-granting if the admin still wants it.
    membership.is_guest = False
    membership.bypass_sso = False
    membership.save(update_fields=["is_guest", "bypass_sso", "updated_at"])

    log_activity(
        organization_id=membership.organization_id,
        team_id=None,
        user=by,
        was_impersonated=False,
        item_id=membership.id,
        scope="OrganizationMembership",
        activity="promoted_from_guest",
        detail=Detail(
            name=membership.user.email if membership.user else None,
            changes=[
                Change(
                    type="OrganizationMembership",
                    action="changed",
                    field="is_guest",
                    before=True,
                    after=False,
                )
            ],
        ),
    )

    return removed
