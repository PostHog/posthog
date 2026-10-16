"""Convert legacy dashboard collaborator permissions into access-control rows.

Run by the ``ee`` data migration that retires ``DashboardPrivilege``. It takes the historical
models Django hands a ``RunPython`` and reads the raw ``restriction_level`` column, because the
``Dashboard`` model field is untracked in the same deploy. A self-hosted instance upgrading with
collaborator-restricted dashboards must be converted before the legacy model and its checks go,
otherwise ``UserAccessControl`` falls back to editor access and previously excluded members can
edit the dashboard and enable public sharing.
"""

from typing import Any

from django.db import transaction
from django.db.models import F, Q

import structlog

logger = structlog.get_logger(__name__)

# Mirrors `ordered_access_levels("dashboard")`.
DASHBOARD_ACCESS_LEVELS = ("none", "viewer", "editor", "manager")
EVERYONE_IN_PROJECT_CAN_EDIT = 21
ONLY_COLLABORATORS_CAN_EDIT = 37
ROLE_BASED_ACCESS_FEATURE = "role_based_access"


def _is_feature_available(organization: Any, feature: str) -> bool:
    return any(
        product_feature and product_feature.get("key") == feature
        for product_feature in (organization.available_product_features or [])
    )


def _has_dashboard_role_access(
    *,
    AccessControl: Any,
    RoleMembership: Any,
    organization: Any,
    dashboard_id: int,
    team_id: int,
    user_id: int,
) -> bool:
    if not _is_feature_available(organization, ROLE_BASED_ACCESS_FEATURE):
        return False

    role_ids = (
        RoleMembership.objects.filter(user_id=user_id, role__organization_id=organization.id)
        .filter(
            Q(organization_member__isnull=True) | Q(organization_member__organization_id=F("role__organization_id")),
        )
        .values("role_id")
    )
    return (
        AccessControl.objects.filter(
            team_id=team_id,
            resource="dashboard",
            organization_member__isnull=True,
            role_id__in=role_ids,
        )
        .filter(Q(resource_id=str(dashboard_id)) | Q(resource_id__isnull=True))
        .exists()
    )


def _ensure_dashboard_access_control(
    *,
    AccessControl: Any,
    team_id: int,
    dashboard_id: int,
    organization_member: Any,
    access_level: str,
) -> None:
    access_control = AccessControl.objects.filter(
        team_id=team_id,
        resource="dashboard",
        resource_id=str(dashboard_id),
        organization_member=organization_member,
        role__isnull=True,
    ).first()
    if access_control is None:
        AccessControl.objects.create(
            team_id=team_id,
            access_level=access_level,
            resource="dashboard",
            resource_id=str(dashboard_id),
            organization_member=organization_member,
        )
        return

    if access_control.access_level in DASHBOARD_ACCESS_LEVELS:
        return

    logger.warning(
        "Replacing invalid dashboard access level during migration",
        access_control_id=access_control.id,
        invalid_access_level=access_control.access_level,
        replacement_access_level=access_level,
    )
    access_control.access_level = access_level
    access_control.save(update_fields=["access_level"])


def rbac_dashboard_access_control_migration(apps: Any, schema_editor: Any) -> None:
    """Convert restriction-level-37 dashboards and their ``DashboardPrivilege`` rows.

    For each restricted dashboard this creates a default viewer access-control row, turns every
    collaborator privilege into an editor row (unless a role rule already grants dashboard
    access), deletes the privilege, and moves the dashboard to restriction level 21.
    """
    Organization = apps.get_model("posthog", "Organization")
    OrganizationMembership = apps.get_model("posthog", "OrganizationMembership")
    AccessControl = apps.get_model("ee", "AccessControl")
    RoleMembership = apps.get_model("ee", "RoleMembership")
    DashboardPrivilege = apps.get_model("ee", "DashboardPrivilege")
    db_alias = schema_editor.connection.alias

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT d.id, d.team_id, t.organization_id
            FROM posthog_dashboard d
            JOIN posthog_team t ON t.id = d.team_id
            WHERE d.restriction_level = %s
            """,
            [ONLY_COLLABORATORS_CAN_EDIT],
        )
        restricted_dashboards = cursor.fetchall()

    if not restricted_dashboards:
        return

    organization_ids = {organization_id for _, _, organization_id in restricted_dashboards}
    organizations = {
        organization.id: organization
        for organization in Organization.objects.using(db_alias).filter(id__in=organization_ids)
    }

    for dashboard_id, team_id, organization_id in restricted_dashboards:
        organization = organizations[organization_id]
        with transaction.atomic(using=db_alias):
            _ensure_dashboard_access_control(
                AccessControl=AccessControl,
                team_id=team_id,
                dashboard_id=dashboard_id,
                organization_member=None,
                access_level="viewer",
            )

            privileges = list(
                DashboardPrivilege.objects.using(db_alias)
                .filter(dashboard_id=dashboard_id)
                .values_list("id", "user_id")
            )
            for privilege_id, user_id in privileges:
                org_membership = (
                    OrganizationMembership.objects.using(db_alias)
                    .filter(user_id=user_id, organization_id=organization_id)
                    .first()
                )
                if org_membership is None:
                    logger.warning(
                        "No organization membership found for user",
                        user_id=user_id,
                        dashboard_id=dashboard_id,
                    )
                    continue

                if _has_dashboard_role_access(
                    AccessControl=AccessControl,
                    RoleMembership=RoleMembership,
                    organization=organization,
                    dashboard_id=dashboard_id,
                    team_id=team_id,
                    user_id=user_id,
                ):
                    logger.info(
                        "Preserving role-based dashboard access for collaborator",
                        dashboard_id=dashboard_id,
                        user_id=user_id,
                    )
                else:
                    _ensure_dashboard_access_control(
                        AccessControl=AccessControl,
                        team_id=team_id,
                        dashboard_id=dashboard_id,
                        organization_member=org_membership,
                        access_level="editor",
                    )

                DashboardPrivilege.objects.using(db_alias).filter(id=privilege_id).delete()
                logger.info(
                    "Migrated dashboard privilege to access control",
                    dashboard_id=dashboard_id,
                    user_id=user_id,
                    team_id=team_id,
                )

            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE posthog_dashboard SET restriction_level = %s WHERE id = %s",
                    [EVERYONE_IN_PROJECT_CAN_EDIT, dashboard_id],
                )
