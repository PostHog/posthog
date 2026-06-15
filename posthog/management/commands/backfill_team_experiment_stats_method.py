from django.core.management.base import BaseCommand

from posthog.models import Organization, Team


class Command(BaseCommand):
    help = "Backfill default_experiment_stats_method from Organization to Team"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of organizations to process before printing progress (default: 1000)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        # Get orgs with non-default stats method (frequentist)
        # Most orgs will have bayesian (default) or null, so this should be a small subset
        orgs_queryset = Organization.objects.exclude(default_experiment_stats_method__isnull=True).exclude(
            default_experiment_stats_method="bayesian"
        )

        org_count = orgs_queryset.count()
        self.stdout.write(f"Found {org_count} organizations with non-default experiment stats method")

        if org_count == 0:
            self.stdout.write("Nothing to backfill.")
            return

        total_teams = 0
        processed_orgs = 0

        # Use iterator() to avoid loading all orgs into memory
        for org in orgs_queryset.only("id", "name", "default_experiment_stats_method").iterator(chunk_size=batch_size):
            team_count = (
                Team.objects.filter(organization_id=org.id).update(
                    default_experiment_stats_method=org.default_experiment_stats_method
                )
                if not dry_run
                else Team.objects.filter(organization_id=org.id).count()
            )

            total_teams += team_count
            processed_orgs += 1

            if processed_orgs % batch_size == 0:
                self.stdout.write(f"Progress: {processed_orgs}/{org_count} orgs processed, {total_teams} teams updated")

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(
            f"\n{'Dry run complete' if dry_run else 'Backfill complete'}. {action} {total_teams} teams across {processed_orgs} organizations."
        )
