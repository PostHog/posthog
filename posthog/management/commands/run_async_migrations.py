import logging
from collections.abc import Sequence

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand

import structlog
from semantic_version.base import Version

from posthog.async_migrations.runner import complete_migration, is_migration_dependency_fulfilled, start_async_migration
from posthog.async_migrations.setup import ALL_ASYNC_MIGRATIONS, setup_async_migrations, setup_model
from posthog.constants import FROZEN_POSTHOG_VERSION
from posthog.models.async_migration import (
    AsyncMigration,
    AsyncMigrationError,
    MigrationStatus,
    get_async_migrations_by_status,
    is_async_migration_complete,
)
from posthog.models.instance_setting import get_instance_setting

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


def get_necessary_migrations() -> Sequence[AsyncMigration]:
    necessary_migrations: list[AsyncMigration] = []
    for migration_name, definition in sorted(ALL_ASYNC_MIGRATIONS.items()):
        if is_async_migration_complete(migration_name):
            continue

        sm = setup_model(migration_name, definition)

        if FROZEN_POSTHOG_VERSION > Version(sm.posthog_max_version):
            necessary_migrations.append(sm)

    return necessary_migrations


class Command(BaseCommand):
    help = "Run async migrations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exits with a non-zero status if required unapplied migrations exist.",
        )
        parser.add_argument(
            "--plan",
            action="store_true",
            help="Show the async migrations that will run",
        )
        parser.add_argument(
            "--complete-noop-migrations",
            action="store_true",
            help="For any migrations that would be no-ops to apply, mark them as complete.",
        )

    def handle(self, *args, **options):
        setup_async_migrations(ignore_posthog_version=True)
        necessary_migrations = get_necessary_migrations()

        if options["check"]:
            handle_check(necessary_migrations)
        elif options["plan"]:
            handle_plan(necessary_migrations)
        elif options["complete_noop_migrations"]:
            handle_complete_noop_migrations()
        else:
            handle_run(necessary_migrations)


def handle_check(necessary_migrations: Sequence[AsyncMigration]):
    if not get_instance_setting("ASYNC_MIGRATIONS_BLOCK_UPGRADE"):
        return

    if necessary_migrations:
        logger.critical(
            "\n".join(
                [
                    "Stopping PostHog!",
                    f"Required async migration{' is' if len(necessary_migrations) == 1 else 's are'} not completed:",
                    *(f"- {migration.get_name_with_requirements()}" for migration in necessary_migrations),
                    "See more in Docs: https://posthog.com/docs/self-host/configure/async-migrations/overview",
                ]
            )
        )
        exit(1)

    running_migrations = get_async_migrations_by_status([MigrationStatus.Running, MigrationStatus.Starting])
    if running_migrations.exists():
        logger.critical(
            "\n".join(
                [
                    "Stopping PostHog!",
                    f"Async migration {running_migrations[0].name} is currently running. If you're trying to update PostHog, wait for it to finish before proceeding",
                    "See more in Docs: https://posthog.com/docs/self-host/configure/async-migrations/overview",
                ]
            )
        )
        exit(1)

    errored_migrations = get_async_migrations_by_status([MigrationStatus.Errored])
    if errored_migrations.exists():
        logger.error(
            "\n".join(
                [
                    f"Stopping PostHog!",
                    "Some async migrations are currently in an 'Errored' state. If you're trying to update PostHog, please make sure they complete successfully first:",
                    *(f"- {migration.name}" for migration in errored_migrations),
                    "See more in Docs: https://posthog.com/docs/self-host/configure/async-migrations/overview",
                ]
            )
        )
        exit(1)


def handle_run(necessary_migrations: Sequence[AsyncMigration]):
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


def handle_plan(necessary_migrations: Sequence[AsyncMigration]):
    if not necessary_migrations:
        logger.info("Async migrations up to date!")
    else:
        logger.warning(
            f"Required async migration{' is' if len(necessary_migrations) == 1 else 's are'} not completed:\n"
            "\n".join(f"- {migration.get_name_with_requirements()}" for migration in necessary_migrations)
        )


def handle_complete_noop_migrations():
    """
    Some migrations are no-ops to apply, i.e. they would not have any effect on
    schema or data within ClickHouse, thus, assuming their dependencies are
    already complete, we can complete them also.
    """
    for migration_name, definition in sorted(ALL_ASYNC_MIGRATIONS.items()):
        if is_async_migration_complete(migration_name):
            continue

        sm = setup_model(migration_name, definition)

        is_required = ALL_ASYNC_MIGRATIONS[migration_name].is_required()
        if not is_required:
            dependency_ok, _ = is_migration_dependency_fulfilled(migration_name)
            if dependency_ok:
                complete_migration(sm)
