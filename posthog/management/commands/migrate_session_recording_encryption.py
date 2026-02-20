import random

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from posthog.models.team import Team


class Command(BaseCommand):
    help = "Enable or disable session recording encryption for teams"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--enable", action="store_true", help="Enable encryption for selected teams")
        group.add_argument("--disable", action="store_true", help="Disable encryption for selected teams")

        parser.add_argument("--team-id", type=int, action="append", help="Target specific team IDs (repeatable)")
        parser.add_argument(
            "--organization-id",
            type=int,
            action="append",
            help="Target all teams in specific organizations (repeatable)",
        )
        parser.add_argument(
            "--percentage", type=float, help="Enable/disable for a percentage (0-100) of eligible teams"
        )
        parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying them")
        parser.add_argument("--batch-size", type=int, default=100, help="Number of teams per batch for DB updates")
        parser.add_argument("--seed", type=int, help="Random seed for reproducible percentage-based selection")

    def handle(self, *args, **options):
        enable = options["enable"]
        team_ids = options["team_id"]
        organization_ids = options["organization_id"]
        percentage = options["percentage"]
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        seed = options["seed"]

        if not team_ids and not organization_ids and percentage is None:
            raise CommandError("At least one of --team-id, --organization-id, or --percentage must be provided")

        if percentage is not None and not (0 <= percentage <= 100):
            raise CommandError("--percentage must be between 0 and 100")

        if batch_size <= 0:
            raise CommandError("--batch-size must be a positive integer")

        target_value = True if enable else False
        action = "Enabling" if enable else "Disabling"

        try:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Starting session recording encryption migration: {action}" + (" (DRY RUN)" if dry_run else "")
                )
            )

            filters = Q()
            if team_ids:
                filters |= Q(id__in=team_ids)
            if organization_ids:
                filters |= Q(organization_id__in=organization_ids)

            queryset = Team.objects.all().order_by("id").only("id", "session_recording_encryption")

            if filters:
                queryset = queryset.filter(filters)

            # Exclude teams already in the target state
            if target_value:
                queryset = queryset.exclude(session_recording_encryption=True)
            else:
                queryset = queryset.filter(session_recording_encryption=True)

            target_ids = list(queryset.values_list("id", flat=True))

            if percentage is not None:
                sample_size = min(int(len(target_ids) * percentage / 100), len(target_ids))
                if seed is not None:
                    random.seed(seed)
                target_ids = random.sample(target_ids, sample_size) if sample_size > 0 else []

            total_teams_migrated = 0

            for i in range(0, len(target_ids), batch_size):
                batch_ids = target_ids[i : i + batch_size]
                for team_id in batch_ids:
                    self.stdout.write(self.style.SUCCESS(f"{'Would update' if dry_run else 'Updating'} team {team_id}"))

                if not dry_run and batch_ids:
                    self.stdout.write(self.style.SUCCESS("Writing batch..."))
                    Team.objects.filter(id__in=batch_ids).update(session_recording_encryption=target_value)

                total_teams_migrated += len(batch_ids)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Success - {total_teams_migrated} teams updated" + (" (DRY RUN)" if dry_run else "")
                )
            )
        except CommandError:
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error occurred: {e}"))
            raise
