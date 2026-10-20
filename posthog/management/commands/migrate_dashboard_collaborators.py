import argparse
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from posthog.rbac.migrations.rbac_dashboard_migration import rbac_dashboard_access_control_migration

from products.dashboards.backend.models.dashboard import Dashboard


class Command(BaseCommand):
    help = "Migrate legacy dashboard collaborator access to access control"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--org-ids",
            type=str,
            help="Comma-separated organization UUIDs to limit the migration. Omit to process all eligible organizations.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the dashboards that would be migrated without making changes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dashboards = Dashboard.objects.filter(restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT)
        org_ids_input = options.get("org_ids")
        if org_ids_input is not None:
            try:
                requested_org_ids = {UUID(org_id.strip()) for org_id in org_ids_input.split(",") if org_id.strip()}
            except ValueError as error:
                raise CommandError("--org-ids must be a comma-separated list of organization UUIDs.") from error
            if not requested_org_ids:
                raise CommandError("--org-ids must include at least one organization UUID.")
            dashboards = dashboards.filter(team__organization_id__in=requested_org_ids)

        dashboard_count = dashboards.count()
        organization_ids = list(
            dashboards.values_list("team__organization_id", flat=True).distinct().order_by("team__organization_id")
        )
        organization_count = len(organization_ids)

        if dashboard_count == 0:
            self.stdout.write("No dashboards need collaborator migration.")
            return

        dashboard_label = "dashboard" if dashboard_count == 1 else "dashboards"
        organization_label = "organization" if organization_count == 1 else "organizations"
        if options.get("dry_run"):
            self.stdout.write(
                f"Would migrate {dashboard_count} {dashboard_label} across {organization_count} {organization_label}."
            )
            return

        for organization_id in organization_ids:
            rbac_dashboard_access_control_migration(organization_id)

        self.stdout.write(
            self.style.SUCCESS(
                f"Migrated collaborator access for {dashboard_count} {dashboard_label} "
                f"across {organization_count} {organization_label}."
            )
        )
