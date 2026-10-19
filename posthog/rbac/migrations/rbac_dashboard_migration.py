"""Convert legacy dashboard collaborator permissions into access-control rows.

Use historical models and the raw restriction_level column because the Dashboard field leaves
Django's state in the same deploy. The member rules preserve the intersection of the existing
ACL and the collaborator permission; the default limits broader grants for future members.
"""

from typing import Any

from django.db import transaction
from django.db.models import F, Q

EVERYONE_IN_PROJECT_CAN_EDIT = 21
ONLY_COLLABORATORS_CAN_EDIT = 37
# Mirrors `ordered_access_levels("dashboard")`.
DASHBOARD_ACCESS_LEVELS = ("none", "viewer", "editor", "manager")


def _is_feature_available(organization: Any, feature: str) -> bool:
    return any(
        product_feature and product_feature.get("key") == feature
        for product_feature in (organization.available_product_features or [])
    )


def _level_from_rows(rows: list[Any], *, most_specific: bool, levels: tuple[str, ...], default: str) -> str:
    if not rows:
        return default
    if most_specific:
        member_rows = [row for row in rows if row.organization_member_id is not None]
        role_rows = [row for row in rows if row.role_id is not None]
        rows = member_rows or role_rows or rows
    return max((row.access_level for row in rows), key=levels.index)


def _dashboard_level(object_rows: list[Any], resource_rows: list[Any], *, most_specific: bool) -> str:
    explicit_rows = [row for row in object_rows if row.organization_member_id is not None or row.role_id is not None]
    if most_specific or explicit_rows:
        if object_rows:
            return _level_from_rows(
                object_rows if most_specific else explicit_rows,
                most_specific=most_specific,
                levels=DASHBOARD_ACCESS_LEVELS,
                default="editor",
            )
    if (
        object_rows
        and _level_from_rows(object_rows, most_specific=False, levels=DASHBOARD_ACCESS_LEVELS, default="editor")
        == "none"
    ):
        return "none"
    return _level_from_rows(
        resource_rows or object_rows,
        most_specific=most_specific,
        levels=DASHBOARD_ACCESS_LEVELS,
        default="editor",
    )


def rbac_dashboard_access_control_migration(apps: Any, schema_editor: Any) -> None:
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
            ORDER BY d.id
            """,
            [ONLY_COLLABORATORS_CAN_EDIT],
        )
        restricted_dashboards = cursor.fetchall()

    for dashboard_id, team_id, organization_id in restricted_dashboards:
        with transaction.atomic(using=db_alias):
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT created_by_id FROM posthog_dashboard WHERE id = %s AND restriction_level = %s FOR UPDATE",
                    [dashboard_id, ONLY_COLLABORATORS_CAN_EDIT],
                )
                dashboard = cursor.fetchone()
            if dashboard is None:
                continue

            organization = Organization.objects.using(db_alias).get(id=organization_id)
            if _is_feature_available(organization, "access_control"):
                memberships = list(
                    OrganizationMembership.objects.using(db_alias).filter(organization_id=organization_id)
                )
                role_ids_by_user: dict[int, set[Any]] = {}
                if _is_feature_available(organization, "role_based_access"):
                    roles = (
                        RoleMembership.objects.using(db_alias)
                        .filter(role__organization_id=organization_id)
                        .filter(
                            Q(organization_member__isnull=True)
                            | Q(organization_member__organization_id=F("role__organization_id"))
                        )
                        .values_list("user_id", "role_id")
                    )
                    for user_id, role_id in roles:
                        role_ids_by_user.setdefault(user_id, set()).add(role_id)
                rows = list(
                    AccessControl.objects.using(db_alias)
                    .filter(team_id=team_id)
                    .filter(
                        Q(resource="dashboard", resource_id=str(dashboard_id))
                        | Q(resource="dashboard", resource_id__isnull=True)
                        | Q(resource="project", resource_id=str(team_id))
                    )
                )
                privileges = dict(
                    DashboardPrivilege.objects.using(db_alias)
                    .filter(dashboard_id=dashboard_id)
                    .values_list("user_id", "level")
                )
                levels_by_member: dict[int, str] = {}
                for membership in memberships:
                    role_ids = role_ids_by_user.get(membership.user_id, set())
                    member_rows = [
                        row
                        for row in rows
                        if (row.organization_member_id is None and row.role_id is None)
                        or (row.organization_member_id == membership.id and row.role_id is None)
                        or (row.organization_member_id is None and row.role_id in role_ids)
                    ]
                    most_specific = organization.uses_most_specific_access_resolution
                    level = _dashboard_level(
                        [row for row in member_rows if row.resource == "dashboard" and row.resource_id is not None],
                        [row for row in member_rows if row.resource == "dashboard" and row.resource_id is None],
                        most_specific=most_specific,
                    )
                    project_rows = [row for row in member_rows if row.resource == "project"]
                    project_overrides = [
                        row for row in project_rows if row.organization_member_id is not None or row.role_id is not None
                    ]
                    project_level = _level_from_rows(
                        project_overrides or project_rows,
                        most_specific=most_specific,
                        levels=("none", "member", "admin"),
                        default="admin",
                    )
                    can_edit = (
                        membership.user_id == dashboard[0]
                        or membership.level >= 8
                        or project_level == "admin"
                        or privileges.get(membership.user_id, 21) >= 37
                    )
                    levels_by_member[membership.id] = level if can_edit or level in ("none", "viewer") else "viewer"

                # Snapshot the intersection of the old ACL and collaborator rules as member rules.
                # Keeping object-role grants would let them override a member's migrated denial.
                AccessControl.objects.using(db_alias).filter(
                    team_id=team_id, resource="dashboard", resource_id=str(dashboard_id)
                ).delete()
                AccessControl.objects.using(db_alias).bulk_create(
                    [
                        AccessControl(
                            team_id=team_id,
                            resource="dashboard",
                            resource_id=str(dashboard_id),
                            access_level="viewer",
                            limit_resource_access=True,
                        ),
                        *[
                            AccessControl(
                                team_id=team_id,
                                resource="dashboard",
                                resource_id=str(dashboard_id),
                                organization_member_id=membership.id,
                                access_level=levels_by_member[membership.id],
                            )
                            for membership in memberships
                        ],
                    ],
                    batch_size=1000,
                )

            DashboardPrivilege.objects.using(db_alias).filter(
                dashboard_id=dashboard_id,
                user_id__in=OrganizationMembership.objects.using(db_alias)
                .filter(organization_id=organization_id)
                .values("user_id"),
            ).delete()
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE posthog_dashboard SET restriction_level = %s WHERE id = %s",
                    [EVERYONE_IN_PROJECT_CAN_EDIT, dashboard_id],
                )
