from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from posthog.models import Team
from posthog.sampling import sample_on_property


class Command(BaseCommand):
    help = """
    Sets the recorder script for a sample of teams based on team ID hashing.

    Example usage:
        python manage.py set_recorder_script --script my-recorder --sample-rate 0.1
        python manage.py set_recorder_script --script my-recorder --sample-rate 0.5 --dry-run
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--script",
            type=str,
            required=True,
            help="The recorder script name to set in extra_settings",
        )
        parser.add_argument(
            "--sample-rate",
            type=float,
            required=True,
            help="Sample rate (0.0 to 1.0) for selecting teams",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which teams would be updated without actually updating them",
        )

    def handle(self, *args, **options):
        script = options["script"]
        sample_rate = options["sample_rate"]
        dry_run = options["dry_run"]

        if not 0 <= sample_rate <= 1:
            raise CommandError("Sample rate must be between 0.0 and 1.0")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

        teams = Team.objects.filter(
            Q(extra_settings__isnull=True) | ~Q(extra_settings__has_key="recorder_script")
        ).only("id", "extra_settings")

        total_teams = teams.count()
        self.stdout.write(f"Found {total_teams} teams without recorder_script set")

        updated_count = 0
        sampled_count = 0

        for team in teams.iterator(chunk_size=1000):
            if sample_on_property(str(team.id), sample_rate):
                sampled_count += 1

                if not dry_run:
                    if team.extra_settings is None:
                        team.extra_settings = {}
                    team.extra_settings["recorder_script"] = script
                    # Using save() to trigger post_save signals for cache invalidation
                    team.save(update_fields=["extra_settings"])
                    updated_count += 1

                    if updated_count % 1000 == 0:
                        self.stdout.write(f"Updated {updated_count} teams so far...")

        percentage = (sampled_count / total_teams * 100) if total_teams > 0 else 0
        self.stdout.write(
            self.style.SUCCESS(f"Sampled {sampled_count} teams ({percentage:.1f}%) using sample rate {sample_rate}")
        )

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Would update {sampled_count} teams with script: {script}"))
            return

        self.stdout.write(
            self.style.SUCCESS(f"Successfully updated {updated_count} teams with recorder script: {script}")
        )
