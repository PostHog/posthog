from typing import Dict, Optional

from django.core.exceptions import ImproperlyConfigured
from infi.clickhouse_orm.utils import import_submodules
from semantic_version.base import SimpleSpec, Version

from posthog.settings import AUTO_START_SPECIAL_MIGRATIONS, DEBUG, E2E_TESTING, SKIP_SERVICE_VERSION_REQUIREMENTS, TEST
from posthog.special_migrations.definition import SpecialMigrationDefinition
from posthog.utils import print_warning
from posthog.version import VERSION

ALL_SPECIAL_MIGRATIONS: Dict[str, SpecialMigrationDefinition] = {}

SPECIAL_MIGRATION_TO_DEPENDENCY: Dict[str, Optional[str]] = {}
DEPENDENCY_TO_SPECIAL_MIGRATION: Dict[Optional[str], str] = {}


POSTHOG_VERSION = Version(VERSION)


def setup_special_migrations():
    from posthog.models.special_migration import SpecialMigration, get_all_completed_special_migrations

    if TEST or E2E_TESTING or SKIP_SERVICE_VERSION_REQUIREMENTS:
        print_warning(["Skipping special migrations setup. This is unsafe in production!"])
        return

    all_migrations = import_submodules("posthog.special_migrations.migrations")

    if DEBUG:
        all_migrations["example"] = import_submodules("posthog.special_migrations.examples")["example"]

    for name, module in all_migrations.items():
        ALL_SPECIAL_MIGRATIONS[name] = module.Migration()

    applied_migrations = set(instance.name for instance in get_all_completed_special_migrations())
    unapplied_migrations = set(ALL_SPECIAL_MIGRATIONS.keys()) - applied_migrations

    first_migration = None
    for migration_name, migration in ALL_SPECIAL_MIGRATIONS.items():

        SpecialMigration.objects.get_or_create(
            name=migration_name,
            description=migration.description,
            posthog_max_version=migration.posthog_max_version,
            posthog_min_version=migration.posthog_min_version,
        )

        dependency = migration.depends_on

        if not dependency:
            if first_migration:
                raise ImproperlyConfigured(
                    "Two or more special migrations have no dependency. Make sure only the first migration has no dependency."
                )

            first_migration = migration_name

        SPECIAL_MIGRATION_TO_DEPENDENCY[migration_name] = dependency

        for key, val in SPECIAL_MIGRATION_TO_DEPENDENCY.items():
            DEPENDENCY_TO_SPECIAL_MIGRATION[val] = key

        if migration_name in unapplied_migrations and POSTHOG_VERSION > Version(migration.posthog_max_version):
            raise ImproperlyConfigured(f"Migration {migration_name} is required for PostHog versions above {VERSION}.")

    if AUTO_START_SPECIAL_MIGRATIONS and first_migration:
        kickstart_migration_if_possible(first_migration, applied_migrations)


def kickstart_migration_if_possible(migration_name: str, applied_migrations: set):
    # look for an unapplied migration an try to run it
    while migration_name in applied_migrations:
        migration_name = DEPENDENCY_TO_SPECIAL_MIGRATION.get(migration_name) or ""
        if not migration_name:
            return

    from posthog.special_migrations.runner import run_next_migration

    run_next_migration(migration_name)
