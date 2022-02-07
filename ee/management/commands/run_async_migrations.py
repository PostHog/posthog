import structlog
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand
from semantic_version.base import Version

from posthog.async_migrations.runner import complete_migration, is_migration_dependency_fulfilled, start_async_migration
from posthog.async_migrations.setup import ALL_ASYNC_MIGRATIONS, POSTHOG_VERSION, setup_async_migrations
from posthog.models.async_migration import AsyncMigration, AsyncMigrationError, MigrationStatus

logger = structlog.get_logger(__name__)


def get_necessary_migrations():
    necessary_migrations = []
    for migration_name, definition in sorted(ALL_ASYNC_MIGRATIONS.items()):
        sm = AsyncMigration.objects.get_or_create(name=migration_name)[0]

        sm.description = definition.description
        sm.posthog_max_version = definition.posthog_max_version
        sm.posthog_min_version = definition.posthog_min_version

        sm.save()

        is_migration_required = ALL_ASYNC_MIGRATIONS[migration_name].is_required()

        if is_migration_required:
            if POSTHOG_VERSION > Version(sm.posthog_max_version):
                necessary_migrations.append(sm)
        else:
            dependency_ok, _ = is_migration_dependency_fulfilled(migration_name)
            if dependency_ok:
                complete_migration(sm)

    return necessary_migrations


class Command(BaseCommand):
    help = "Run async migrations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--plan", action="store_true", help="Show the async migrations that will run",
        )

    def handle(self, *args, **options):

        setup_async_migrations(ignore_posthog_version=True)
        necessary_migrations = get_necessary_migrations()

        if options["plan"]:
            print()

            if len(necessary_migrations) == 0:
                print("Async migrations up to date!")
                return

            print("List of async migrations to be applied:")

            for migration in necessary_migrations:
                print(f"- {migration.name}")

            print()
            return

        for migration in necessary_migrations:
            logger.info(f"Applying async migration {migration.name}")
            started_successfully = start_async_migration(migration.name, ignore_posthog_version=True)
            migration.refresh_from_db()
            if not started_successfully or migration.status != MigrationStatus.CompletedSuccessfully:
                last_error = AsyncMigrationError.objects.filter(async_migration=migration).last()
                last_error_msg = f", last error: {last_error.description}" if last_error else ""
                logger.info(f"Unable to complete async migration {migration.name}{last_error_msg}.")
                raise ImproperlyConfigured(
                    f"Migrate job failed because necessary async migration {migration.name} could not complete."
                )

            logger.info(f"✅ Migration {migration.name} successful")
