import logging
from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand

import structlog

from posthog.models.organization import Organization
from posthog.rbac.migrations.rbac_dashboard_migration import rbac_dashboard_access_control_migration
from posthog.rbac.migrations.rbac_feature_flag_migration import rbac_feature_flag_role_access_migration
from posthog.rbac.migrations.rbac_team_migration import rbac_team_access_control_migration

from ee.models.rbac.organization_resource_access import OrganizationResourceAccess
from ee.models.rbac.role import Role

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Run RBAC migrations for specified organizations"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--org-ids",
            type=str,
            dest="org_ids",
            help="Comma-separated list of organization IDs",
        )
        group.add_argument(
            "--rollout-date",
            type=str,
            help="Date from which to start the rollout (YYYY-MM-DD format)",
            dest="rollout_date",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show organizations that would be migrated without actually running the migrations",
        )

    def handle(self, *args, **options):
        org_ids_input = options["org_ids"]
        rollout_date_str = options["rollout_date"]

        if org_ids_input:
            org_ids = [org_id.strip() for org_id in org_ids_input.split(",")]

        elif rollout_date_str:
            self.stdout.write("Finding organizations that need RBAC migration...")

            # Parse rollout date
            try:
                rollout_date = datetime.strptime(rollout_date_str, "%Y-%m-%d").date()
            except ValueError:
                self.stdout.write(self.style.ERROR(f"Invalid date format. Please use YYYY-MM-DD format."))
                return

            self.stdout.write(f"Using rollout date: {rollout_date}")

            # Find organizations that need migration and were created after the rollout date
            all_org_ids = self.find_organizations_needing_migration(rollout_date)
            org_ids = all_org_ids

            if options.get("dry_run"):
                self.stdout.write(
                    f"Would migrate {len(org_ids)} organizations eligible for RBAC migration (created on or after {rollout_date})."
                )
                return

            self.stdout.write(
                f"Found {len(org_ids)} organizations eligible for RBAC migration (created on or after {rollout_date})."
            )

            if not org_ids:
                self.stdout.write(self.style.SUCCESS("No organizations found that need RBAC migration."))
                return

            self.stdout.write(f"Found {len(org_ids)} organizations that need RBAC migration.")

        else:
            self.stdout.write(
                "No organization IDs or rollout date provided. Please specify either --org-ids or --rollout-date."
            )
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
            dashboard_success = org_result["dashboard_migration"]["success"]

            if team_success and ff_success and dashboard_success:
                self.stdout.write(self.style.SUCCESS(f"Organization {org_id} ({org_name}): All migrations successful"))
            else:
                self.stdout.write(self.style.WARNING(f"Organization {org_id} ({org_name}): Some migrations failed"))

                if not team_success:
                    error = org_result["team_migration"]["error"] or "Unknown error"
                    self.stdout.write(self.style.ERROR(f"  Team migration failed: {error}"))

                if not ff_success:
                    error = org_result["feature_flag_migration"]["error"] or "Unknown error"
                    self.stdout.write(self.style.ERROR(f"  Feature flag migration failed: {error}"))

                if not dashboard_success:
                    error = org_result["dashboard_migration"]["error"] or "Unknown error"
                    self.stdout.write(self.style.ERROR(f"  Dashboard migration failed: {error}"))

    def find_organizations_needing_migration(self, rollout_date) -> list[int]:
        """
        Find organizations that need RBAC migration based on the following criteria:
        - Has a team with access_control = True
        - Has an OrganizationResourceAccess row
        - Has a Role with feature flag access settings
        - Has dashboards with restriction_level = 37 (ONLY_COLLABORATORS_CAN_EDIT)
        - Created after the rollout date

        Returns:
            List of organization IDs that need migration
        """
        # Find organizations with teams that have access_control = True
        orgs_with_team_access_control = (
            Organization.objects.filter(team__access_control=True).values_list("id", flat=True).distinct()
        )
        logger.info(f"Found {len(orgs_with_team_access_control)} organizations with team access control")

        # Find organizations with OrganizationResourceAccess rows
        orgs_with_resource_access = OrganizationResourceAccess.objects.values_list(
            "organization_id", flat=True
        ).distinct()
        logger.info(f"Found {len(orgs_with_resource_access)} organizations with resource access")

        # Find organizations with roles that have feature flag access
        orgs_with_feature_flag_roles = (
            Role.objects.filter(feature_flags_access_level__isnull=False)
            .values_list("organization_id", flat=True)
            .distinct()
        )
        logger.info(f"Found {len(orgs_with_feature_flag_roles)} organizations with feature flag roles")

        # Find organizations with dashboards that have restriction level 37
        from posthog.models.dashboard import Dashboard

        orgs_with_restricted_dashboards = (
            Organization.objects.filter(
                team__dashboard__restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
            )
            .values_list("id", flat=True)
            .distinct()
        )
        logger.info(f"Found {len(orgs_with_restricted_dashboards)} organizations with restricted dashboards")

        # Find organizations created after the rollout date
        orgs_after_rollout_date = Organization.objects.filter(created_at__date__gte=rollout_date).values_list(
            "id", flat=True
        )
        logger.info(f"Found {len(orgs_after_rollout_date)} organizations created on or after {rollout_date}")

        # Combine all organization IDs
        needs_migration = (
            set(orgs_with_team_access_control)
            | set(orgs_with_resource_access)
            | set(orgs_with_feature_flag_roles)
            | set(orgs_with_restricted_dashboards)
        )
        logger.info(f"Found {len(needs_migration)} total organizations that need migration")

        eligible_orgs = needs_migration & set(orgs_after_rollout_date)
        logger.info(
            f"Found {len(eligible_orgs)} organizations eligible for migration (created on or after {rollout_date})"
        )

        all_org_ids = eligible_orgs

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
                "dashboard_migration": {"success": False, "error": None},
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

            # Run dashboard access control migration
            try:
                rbac_dashboard_access_control_migration(org_id)
                org_result["dashboard_migration"]["success"] = True
                logger.info("Dashboard access control migration successful", organization_id=org_id)
            except Exception as e:
                error_msg = str(e)
                org_result["dashboard_migration"]["error"] = error_msg
                logger.error(
                    "Dashboard access control migration failed", organization_id=org_id, error=error_msg, exc_info=True
                )

            # Update summary counters
            if (
                org_result["team_migration"]["success"]
                and org_result["feature_flag_migration"]["success"]
                and org_result["dashboard_migration"]["success"]
            ):
                results["successful"] += 1
                logger.info("All migrations successful for organization", organization_id=org_id)
            else:
                results["failed"] += 1
                logger.error("Some migrations failed for organization", organization_id=org_id)

            results["details"].append(org_result)

        return results
