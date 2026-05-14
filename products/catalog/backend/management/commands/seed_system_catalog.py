"""Seed the catalog with system.* tables for one or more teams.

Idempotent — safe to re-run after `system.py` changes merge, and safe to run on
deploy for backfilling teams that pre-date the Team post_save signal.
"""

from django.core.management.base import BaseCommand, CommandError

from posthog.models.team import Team

from products.catalog.backend.logic import sync_system_tables_for_team


class Command(BaseCommand):
    help = "Upsert CatalogNode/CatalogColumn rows for every system table in SystemTables.children"

    def add_arguments(self, parser) -> None:
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument(
            "--team-id",
            type=int,
            help="Seed a single team by id.",
        )
        target.add_argument(
            "--all",
            action="store_true",
            help="Seed every team in the database.",
        )

    def handle(self, *args, **options) -> None:
        if options["team_id"] is not None:
            if not Team.objects.filter(pk=options["team_id"]).exists():
                raise CommandError(f"Team {options['team_id']} does not exist")
            nodes = sync_system_tables_for_team(options["team_id"])
            self.stdout.write(self.style.SUCCESS(f"Seeded {nodes} system tables for team {options['team_id']}"))
            return

        team_ids = list(Team.objects.values_list("pk", flat=True))
        total = len(team_ids)
        self.stdout.write(f"Seeding system tables for {total} team(s)...")
        for index, team_id in enumerate(team_ids, start=1):
            sync_system_tables_for_team(team_id)
            if index % 100 == 0 or index == total:
                self.stdout.write(f"  {index}/{total}")
        self.stdout.write(self.style.SUCCESS(f"Done — seeded {total} team(s)"))
