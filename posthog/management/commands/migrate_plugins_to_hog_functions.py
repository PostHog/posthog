from django.core.management.base import BaseCommand

from posthog.cdp.migrations import migrate_legacy_plugins


class Command(BaseCommand):
    help = "Migrate plugins to HogFunctions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="If set, will not actually perform the migration, but will print out what would have been done",
        )
        parser.add_argument("--team-ids", type=str, help="Comma separated list of team ids to sync")
        parser.add_argument(
            "--test-mode", action="store_true", help="Whether to just copy as a test function rather than migrate"
        )
        parser.add_argument(
            "--kind",
            type=str,
            help="Whether to migrate destinations or transformations",
            choices=["destination", "transformation"],
        )
        parser.add_argument("--batch-size", type=int, help="The number of plugins to migrate at a time", default=100)
        parser.add_argument("--limit", type=int, help="The number of plugins to migrate", default=None)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        team_ids = options["team_ids"]
        test_mode = options["test_mode"]
        kind = options["kind"]
        batch_size = options["batch_size"]
        limit = options["limit"]
        print("Migrating plugins to hog functions", options)  # noqa: T201

        migrate_legacy_plugins(
            dry_run=dry_run, team_ids=team_ids, test_mode=test_mode, kind=kind, batch_size=batch_size, limit=limit
        )
