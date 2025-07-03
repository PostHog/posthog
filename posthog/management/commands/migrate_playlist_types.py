from django.core.management.base import BaseCommand
from posthog.tasks.migrate_playlist_type import migrate_playlist_type


class Command(BaseCommand):
    help = "Migrate SessionRecordingPlaylist type field based on playlist contents"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="If set, will not actually perform the migration, but will print out what would have been done",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            help="If set, will run the migration asynchronously",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Running in dry run mode, would have updated the following playlists:")
            )

        if options["async"]:
            task = migrate_playlist_type.delay(dry_run=dry_run)
            mode_text = "DRY RUN" if dry_run else "LIVE"
            self.stdout.write(self.style.SUCCESS(f"Task {task.id} started in {mode_text} mode"))
        else:
            migrate_playlist_type(dry_run=dry_run)
            mode_text = "DRY RUN" if dry_run else "LIVE"
            self.stdout.write(self.style.SUCCESS(f"Migration completed in {mode_text} mode"))
