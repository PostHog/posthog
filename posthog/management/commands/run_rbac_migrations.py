import logging
from typing import Any

import structlog
from django.core.management.base import BaseCommand
from django.db.models import Q

from posthog.rbac.migrations.rbac_team_migration import rbac_team_access_control_migration
from posthog.rbac.migrations.rbac_feature_flag_migration import rbac_feature_flag_role_access_migration
from posthog.models.organization import Organization
from ee.models.rbac.organization_resource_access import OrganizationResourceAccess
from ee.models.rbac.role import Role

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Run RBAC migrations for specified organizations"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--org-ids",
            type=str,
            help="Comma-separated list of organization IDs",
        )
        group.add_argument(
            "--backfill",
            action="store_true",
            help="Find and migrate all organizations that need the RBAC migration",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show organizations that would be migrated without actually running the migrations",
        )

    def handle(self, *args, **options):
        if options["org_ids"]:
            org_ids_input = options["org_ids"]
            # Parse comma-separated list of organization IDs
            org_ids = [int(org_id.strip()) for org_id in org_ids_input.split(",")]
        else:  # backfill option
            self.stdout.write("Finding organizations that need RBAC migration...")
            org_ids = self.find_organizations_needing_migration()

            if not org_ids:
                self.stdout.write(self.style.SUCCESS("No organizations found that need RBAC migration."))
                return

            self.stdout.write(f"Found {len(org_ids)} organizations that need RBAC migration.")
            for org_id in org_ids:
                try:
                    org = Organization.objects.get(id=org_id)
                    self.stdout.write(f"  - Organization {org_id}: {org.name}")
                except Organization.DoesNotExist:
                    self.stdout.write(f"  - Organization {org_id}: [Not Found]")

            if options["dry_run"]:
                self.stdout.write(self.style.WARNING("Dry run mode - no migrations were performed."))
                return

        # Run migrations
        results = self.run_migrations_for_organizations(org_ids)

        # Print summary to console
        self.stdout.write(self.style.SUCCESS(f"RBAC Migration Summary:"))
        self.stdout.write(f"Total organizations: {results['total']}")
        self.stdout.write(self.style.SUCCESS(f"Successful migrations: {results['successful']}"))

        if results["failed"] > 0:
            self.stdout.write(self.style.ERROR(f"Failed migrations: {results['failed']}"))
        else:
            self.stdout.write(f"Failed migrations: {results['failed']}")

        # Print detailed results
        self.stdout.write("\nDetailed Results:")
        for org_result in results["details"]:
            org_id = org_result["organization_id"]
            org_name = org_result.get("organization_name", "Unknown")

            if org_result.get("error"):
                self.stdout.write(self.style.ERROR(f"Organization {org_id} ({org_name}): {org_result['error']}"))
                continue

            team_success = org_result["team_migration"]["success"]
            ff_success = org_result["feature_flag_migration"]["success"]

            if team_success and ff_success:
                self.stdout.write(self.style.SUCCESS(f"Organization {org_id} ({org_name}): All migrations successful"))
            else:
                self.stdout.write(self.style.WARNING(f"Organization {org_id} ({org_name}): Some migrations failed"))

                if not team_success:
                    error = org_result["team_migration"]["error"] or "Unknown error"
                    self.stdout.write(self.style.ERROR(f"  Team migration failed: {error}"))

                if not ff_success:
                    error = org_result["feature_flag_migration"]["error"] or "Unknown error"
                    self.stdout.write(self.style.ERROR(f"  Feature flag migration failed: {error}"))

    def find_organizations_needing_migration(self) -> list[int]:
        """
        Find organizations that need RBAC migration based on the following criteria:
        - Has a team with access_control = True
        - Has an OrganizationResourceAccess row
        - Has a Role with feature flag access settings

        Returns:
            List of organization IDs that need migration
        """
        # Find organizations with teams that have access_control = True
        orgs_with_team_access_control = (
            Organization.objects.filter(team__access_control=True).values_list("id", flat=True).distinct()
        )

        # Find organizations with OrganizationResourceAccess rows
        orgs_with_resource_access = OrganizationResourceAccess.objects.values_list(
            "organization_id", flat=True
        ).distinct()

        # Find organizations with roles that have feature flag access
        orgs_with_feature_flag_roles = (
            Role.objects.filter(Q(feature_flags_access_level__isnull=False) | Q(feature_flag_access__isnull=False))
            .values_list("organization_id", flat=True)
            .distinct()
        )

        # Combine all organization IDs
        all_org_ids = (
            set(orgs_with_team_access_control) | set(orgs_with_resource_access) | set(orgs_with_feature_flag_roles)
        )

        return sorted(all_org_ids)

    def run_migrations_for_organizations(self, organization_ids: list[int]) -> dict[str, Any]:
        """
        Run RBAC migrations for a list of organizations.

        Args:
            organization_ids: List of organization IDs to run migrations for

        Returns:
            Dictionary with summary of migration results
        """
        results: dict[str, Any] = {"total": len(organization_ids), "successful": 0, "failed": 0, "details": []}

        for org_id in organization_ids:
            org_result: dict[str, Any] = {
                "organization_id": org_id,
                "team_migration": {"success": False, "error": None},
                "feature_flag_migration": {"success": False, "error": None},
            }

            # Verify organization exists
            try:
                org = Organization.objects.get(id=org_id)
                org_result["organization_name"] = org.name
                logger.info("Starting RBAC migrations", organization_id=org_id, organization_name=org.name)
            except Organization.DoesNotExist:
                error_msg = f"Organization with ID {org_id} does not exist"
                org_result["error"] = error_msg
                logger.exception(error_msg)
                results["failed"] += 1
                results["details"].append(org_result)
                continue

            # Run team access control migration
            try:
                rbac_team_access_control_migration(org_id)
                org_result["team_migration"]["success"] = True
                logger.info("Team access control migration successful", organization_id=org_id)
            except Exception as e:
                error_msg = str(e)
                org_result["team_migration"]["error"] = error_msg
                logger.error(
                    "Team access control migration failed", organization_id=org_id, error=error_msg, exc_info=True
                )

            # Run feature flag role access migration
            try:
                rbac_feature_flag_role_access_migration(str(org_id))  # Note: This function expects a string
                org_result["feature_flag_migration"]["success"] = True
                logger.info("Feature flag role access migration successful", organization_id=org_id)
            except Exception as e:
                error_msg = str(e)
                org_result["feature_flag_migration"]["error"] = error_msg
                logger.error(
                    "Feature flag role access migration failed", organization_id=org_id, error=error_msg, exc_info=True
                )

            # Update summary counters
            if org_result["team_migration"]["success"] and org_result["feature_flag_migration"]["success"]:
                results["successful"] += 1
                logger.info("All migrations successful for organization", organization_id=org_id)
            else:
                results["failed"] += 1
                logger.error("Some migrations failed for organization", organization_id=org_id)

            results["details"].append(org_result)

        return results
