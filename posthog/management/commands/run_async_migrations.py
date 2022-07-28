import structlog
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand
from semantic_version.base import Version

from posthog.async_migrations.runner import complete_migration, is_migration_dependency_fulfilled, start_async_migration
from posthog.async_migrations.setup import ALL_ASYNC_MIGRATIONS, POSTHOG_VERSION, setup_async_migrations, setup_model
from posthog.models.async_migration import (
    AsyncMigrationError,
    MigrationStatus,
    get_async_migrations_by_status,
    is_async_migration_complete,
)
from posthog.models.instance_setting import get_instance_setting

logger = structlog.get_logger(__name__)


def get_necessary_migrations():
    necessary_migrations = []
    for migration_name, definition in sorted(ALL_ASYNC_MIGRATIONS.items()):
        if is_async_migration_complete(migration_name):
            continue

        sm = setup_model(migration_name, definition)
        if sm is None:
            continue

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
            "--check", action="store_true", help="Exits with a non-zero status if required unapplied migrations exist."
        )
        parser.add_argument(
            "--plan", action="store_true", help="Show the async migrations that will run",
        )

    def handle(self, *args, **options):

        setup_async_migrations(ignore_posthog_version=True)
        necessary_migrations = get_necessary_migrations()

        if options["check"]:
            handle_check(necessary_migrations)
        elif options["plan"]:
            handle_plan(necessary_migrations)
        else:
            handle_run(necessary_migrations)


def print_necessary_migrations(necessary_migrations):
    print("List of async migrations to be applied:")

    for migration in necessary_migrations:
        print(
            f"- {migration.name} - Available on Posthog versions {migration.posthog_min_version} - {migration.posthog_max_version}"
        )

    print()


def handle_check(necessary_migrations):
    if not get_instance_setting("ASYNC_MIGRATIONS_BLOCK_UPGRADE"):
        return

    if len(necessary_migrations) > 0:
        print_necessary_migrations(necessary_migrations)
        print(
            "Async migrations are not completed. See more info https://posthog.com/docs/self-host/configure/async-migrations/overview"
        )
        exit(1)

    running_migrations = get_async_migrations_by_status([MigrationStatus.Running, MigrationStatus.Starting])
    if running_migrations.exists():
        print(
            f"Async migration {running_migrations[0].name} is currently running. If you're trying to update PostHog, wait for it to finish before proceeding."
        )
        exit(1)

    errored_migrations = get_async_migrations_by_status([MigrationStatus.Errored])
    if errored_migrations.exists():
        print(
            "Some async migrations are currently in an 'Errored' state. If you're trying to update PostHog, please make sure they complete successfully first."
        )
        print()
        print("Errored migrations:")
        for migration in errored_migrations:
            print(f"- {migration.name}")
        exit(1)


def handle_run(necessary_migrations):
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


def handle_plan(necessary_migrations):
    print()

    if len(necessary_migrations) == 0:
        print("Async migrations up to date!")
        return

    print()

    print_necessary_migrations(necessary_migrations)
