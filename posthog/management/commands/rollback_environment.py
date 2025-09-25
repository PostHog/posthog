"""
CLI interface to the existing environments_rollback_migration function.
"""

from django.core.management.base import BaseCommand, CommandError

from posthog.models import Organization, User
from posthog.tasks.environments_rollback import environments_rollback_migration


class Command(BaseCommand):
    help = "Rollback organization environments using source:target team mappings"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=str, required=True, help="Organization UUID to rollback environments for")

        parser.add_argument(
            "--team-mappings",
            type=str,
            required=True,
            help="Comma-separated list of source:target team ID pairs (e.g., '123:456,789:456,101:102')",
        )

        parser.add_argument("--user-id", type=int, help="User ID performing the rollback", required=True)

        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be changed without executing the rollback"
        )

        parser.add_argument("--force", action="store_true", help="Skip interactive confirmation prompts")

    def handle(self, *args, **options):
        org_id = options["org_id"]
        team_mappings = options["team_mappings"]
        user_id = options["user_id"]
        dry_run = options["dry_run"]
        force = options["force"]

        try:
            environment_mappings = self._parse_team_mappings(team_mappings)

            organization = self._get_organization(org_id)

            user = self._get_user(user_id, organization)

            self._display_plan(organization, environment_mappings, user)

            if dry_run:
                self.stdout.write(self.style.SUCCESS("DRY RUN: No changes made."))
                return

            if not force and not self._confirm():
                self.stdout.write("Rollback cancelled.")
                return

            self.stdout.write("Executing rollback...")
            environments_rollback_migration(
                organization_id=organization.id, environment_mappings=environment_mappings, user_id=user.id
            )

            self.stdout.write(self.style.SUCCESS(f"✓ Rollback completed for organization {organization.name}"))

        except Exception as e:
            raise CommandError(f"Rollback failed: {str(e)}")

    def _parse_team_mappings(self, team_mappings: str) -> dict[str, int]:
        """Parse team mappings from 'source:target,source:target' format."""
        mappings = {}

        for mapping in team_mappings.split(","):
            mapping = mapping.strip()
            if not mapping:
                continue

            if ":" not in mapping:
                raise CommandError(f"Invalid mapping format: '{mapping}'. Use 'source:target'")

            source, target = mapping.split(":", 1)
            source_id = int(source.strip())
            target_id = int(target.strip())

            if source_id == target_id:
                raise CommandError(f"Source and target cannot be the same: {source_id}")

            mappings[str(source_id)] = target_id

        if not mappings:
            raise CommandError("No valid team mappings provided")

        return mappings

    def _get_organization(self, org_id: str) -> Organization:
        """Get organization by ID."""
        try:
            return Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            raise CommandError(f"Organization {org_id} not found")

    def _get_user(self, user_id: int, organization: Organization) -> User:
        """Get user for rollback operation."""
        try:
            user = User.objects.get(id=user_id)
            # Verify user is in org
            if not user.organization_memberships.filter(organization=organization).exists():
                raise CommandError(f"User {user_id} is not a member of organization {organization.id}")
            return user
        except User.DoesNotExist:
            raise CommandError(f"User {user_id} not found")

    def _display_plan(self, organization: Organization, mappings: dict[str, int], user: User):
        """Display rollback plan."""
        self.stdout.write(f"\nOrganization: {organization.name} ({organization.id})")
        self.stdout.write(f"User: {user.email} ({user.id})")
        self.stdout.write(f"\nTeam Mappings ({len(mappings)} pairs):")

        for source_id, target_id in mappings.items():
            self.stdout.write(f"  Team {source_id} → Team {target_id}")

    def _confirm(self) -> bool:
        """Get user confirmation."""
        self.stdout.write(self.style.WARNING("\n⚠️  WARNING: This operation cannot be undone!"))
        try:
            response = input("Type 'ROLLBACK' to confirm: ")
            return response.strip() == "ROLLBACK"
        except KeyboardInterrupt:
            return False
