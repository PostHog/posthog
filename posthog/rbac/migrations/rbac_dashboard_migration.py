"""Convert collaborator edit limits without replacing the dashboard's live ACLs.

The legacy column and privileges stay intact for previous-release pods during a rolling deploy.
The separate resource keeps the new limits out of those pods' dashboard ACL resolution.
"""

from typing import Any

from django.db import transaction
from django.db.models import Q

import structlog

logger = structlog.get_logger(__name__)

ONLY_COLLABORATORS_CAN_EDIT = 37
# Mirrors the runtime resource in UserAccessControl without importing live models into a migration.
DASHBOARD_EDIT_LIMIT_RESOURCE = "dashboard_edit_limit"
DASHBOARD_ACCESS_LEVELS = ("none", "viewer", "editor", "manager")


def rbac_dashboard_access_control_migration(apps: Any, schema_editor: Any) -> None:
    OrganizationMembership = apps.get_model("posthog", "OrganizationMembership")
    AccessControl = apps.get_model("ee", "AccessControl")
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
                    "SELECT id FROM posthog_dashboard WHERE id = %s AND restriction_level = %s FOR UPDATE",
                    [dashboard_id, ONLY_COLLABORATORS_CAN_EDIT],
                )
                if cursor.fetchone() is None:
                    continue

            limits = AccessControl.objects.using(db_alias).filter(
                team_id=team_id, resource=DASHBOARD_EDIT_LIMIT_RESOURCE, resource_id=str(dashboard_id)
            )
            if limits.exists():
                continue

            # Invalid rules must not abort every upgrade retry or turn into edit grants.
            repaired_dashboard_rules = (
                AccessControl.objects.using(db_alias)
                .filter(team_id=team_id, resource="dashboard")
                .filter(Q(resource_id=str(dashboard_id)) | Q(resource_id__isnull=True))
                .exclude(access_level__in=DASHBOARD_ACCESS_LEVELS)
                .update(access_level="viewer")
            )
            repaired_project_rules = (
                AccessControl.objects.using(db_alias)
                .filter(team_id=team_id, resource="project", resource_id=str(team_id))
                .exclude(access_level__in=("none", "member", "admin"))
                .update(access_level="none")
            )
            if repaired_dashboard_rules or repaired_project_rules:
                logger.warning(
                    "Repaired invalid access levels during dashboard conversion",
                    dashboard_id=dashboard_id,
                    dashboard_rules=repaired_dashboard_rules,
                    project_rules=repaired_project_rules,
                )

            editor_ids = (
                DashboardPrivilege.objects.using(db_alias)
                .filter(dashboard_id=dashboard_id, level=ONLY_COLLABORATORS_CAN_EDIT)
                .values("user_id")
            )
            memberships = (
                OrganizationMembership.objects.using(db_alias)
                .filter(organization_id=organization_id, user_id__in=editor_ids)
                .values_list("id", flat=True)
            )
            AccessControl.objects.using(db_alias).bulk_create(
                [
                    AccessControl(
                        team_id=team_id,
                        resource=DASHBOARD_EDIT_LIMIT_RESOURCE,
                        resource_id=str(dashboard_id),
                        access_level="viewer",
                    ),
                    *[
                        AccessControl(
                            team_id=team_id,
                            resource=DASHBOARD_EDIT_LIMIT_RESOURCE,
                            resource_id=str(dashboard_id),
                            organization_member_id=membership_id,
                            access_level="editor",
                        )
                        for membership_id in memberships
                    ],
                ],
                batch_size=1000,
            )
