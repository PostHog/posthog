from django.core.management.base import BaseCommand, CommandError

from posthog.cloud_utils import get_cached_instance_license
from posthog.models import Organization
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import BillingProvider


class Command(BaseCommand):
    help = (
        "Clean up orphaned Vercel billing customers. "
        "These are orgs that have billing_provider=vercel in the billing service "
        "but no corresponding OrganizationIntegration in PostHog (due to broken deauthorization webhooks)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "org_ids",
            nargs="*",
            type=str,
            help="Organization IDs to check and clean up",
        )
        parser.add_argument(
            "--file",
            type=str,
            help="Path to a file containing organization IDs, one per line",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be done without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        org_ids = self._collect_org_ids(options)

        if not org_ids:
            raise CommandError("No organization IDs provided. Use positional args or --file.")

        self.stdout.write(f"Processing {len(org_ids)} organization(s){'  [DRY RUN]' if dry_run else ''}")

        license = get_cached_instance_license()
        if not license:
            raise CommandError("No license found - cannot call billing service")

        skipped = 0
        deauthorized = 0
        errors = 0
        not_found = 0

        for org_id in org_ids:
            try:
                organization = Organization.objects.get(id=org_id)
            except Organization.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"  {org_id}: organization not found in PostHog, skipping"))
                not_found += 1
                continue

            has_integration = OrganizationIntegration.objects.filter(
                organization=organization,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            ).exists()

            if has_integration:
                self.stdout.write(self.style.SUCCESS(f"  {org_id}: has Vercel integration, skipping (not orphaned)"))
                skipped += 1
                continue

            org_membership = (
                OrganizationMembership.objects.filter(
                    organization=organization,
                    level__gte=OrganizationMembership.Level.ADMIN,
                )
                .select_related("user")
                .order_by("-level")
                .first()
            )
            if not org_membership:
                self.stdout.write(self.style.WARNING(f"  {org_id}: no admin/owner found, cannot deauthorize, skipping"))
                errors += 1
                continue

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {org_id}: would deauthorize Vercel billing (using user {org_membership.user.email})"
                    )
                )
                deauthorized += 1
                continue

            try:
                billing_manager = BillingManager(license, user=org_membership.user)
                billing_manager.deauthorize(organization, billing_provider=BillingProvider.VERCEL)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {org_id}: deauthorized Vercel billing (using user {org_membership.user.email})"
                    )
                )
                deauthorized += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  {org_id}: failed to deauthorize: {e}"))
                errors += 1

        self.stdout.write("")
        self.stdout.write(f"Done{'  [DRY RUN]' if dry_run else ''}:")
        self.stdout.write(f"  {'Would deauthorize' if dry_run else 'Deauthorized'}: {deauthorized}")
        self.stdout.write(f"  Skipped (has integration): {skipped}")
        self.stdout.write(f"  Not found: {not_found}")
        self.stdout.write(f"  Errors: {errors}")

    def _collect_org_ids(self, options) -> list[str]:
        org_ids = list(options["org_ids"])

        file_path = options.get("file")
        if file_path:
            try:
                with open(file_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            org_ids.append(line)
            except FileNotFoundError:
                raise CommandError(f"File not found: {file_path}")

        return org_ids
