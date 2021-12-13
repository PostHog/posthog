from typing import Dict, Optional

from django.core.exceptions import ImproperlyConfigured
from infi.clickhouse_orm.utils import import_submodules
from semantic_version.base import Version

from posthog.models.special_migration import SpecialMigration, get_all_completed_special_migrations
from posthog.settings import AUTO_START_SPECIAL_MIGRATIONS, DEBUG, TEST
from posthog.special_migrations.definition import SpecialMigrationDefinition
from posthog.version import VERSION

ALL_SPECIAL_MIGRATIONS: Dict[str, SpecialMigrationDefinition] = {}

SPECIAL_MIGRATION_TO_DEPENDENCY: Dict[str, Optional[str]] = {}

# inverted mapping of SPECIAL_MIGRATION_TO_DEPENDENCY
DEPENDENCY_TO_SPECIAL_MIGRATION: Dict[Optional[str], str] = {}


POSTHOG_VERSION = Version(VERSION)

SPECIAL_MIGRATIONS_MODULE_PATH = "posthog.special_migrations.migrations"
SPECIAL_MIGRATIONS_EXAMPLE_MODULE_PATH = "posthog.special_migrations.examples"

all_migrations = import_submodules(SPECIAL_MIGRATIONS_MODULE_PATH)

if DEBUG and not TEST:
    all_migrations["example"] = import_submodules(SPECIAL_MIGRATIONS_EXAMPLE_MODULE_PATH)["example"]

for name, module in all_migrations.items():
    ALL_SPECIAL_MIGRATIONS[name] = module.Migration()


def setup_special_migrations(ignore_posthog_version: bool = False):
    """
    Execute the necessary setup for special migrations to work:
    1. Import all the migration definitions 
    2. Create a database record for each
    3. Check if all migrations necessary for this PostHog version have completed (else don't start)
    4. Populate a dependencies map and in-memory record of migration definitions
    """

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

        if (
            (not ignore_posthog_version)
            and (migration_name in unapplied_migrations)
            and (POSTHOG_VERSION > Version(migration.posthog_max_version))
        ):
            raise ImproperlyConfigured(f"Migration {migration_name} is required for PostHog versions above {VERSION}.")

    for key, val in SPECIAL_MIGRATION_TO_DEPENDENCY.items():
        DEPENDENCY_TO_SPECIAL_MIGRATION[val] = key

    if AUTO_START_SPECIAL_MIGRATIONS and first_migration:
        kickstart_migration_if_possible(first_migration, applied_migrations)


def kickstart_migration_if_possible(migration_name: str, applied_migrations: set):
    """
    Find the last completed migration, look for a migration that depends on it, and try to run it
    """

    while migration_name in applied_migrations:
        migration_name = DEPENDENCY_TO_SPECIAL_MIGRATION.get(migration_name) or ""
        if not migration_name:
            return

    from posthog.special_migrations.runner import run_next_migration

    # start running 30 minutes from now
    run_next_migration(migration_name, after_delay=60 * 30)


def get_special_migration_definition(migration_name: str) -> SpecialMigrationDefinition:
    if TEST:
        return import_submodules(SPECIAL_MIGRATIONS_EXAMPLE_MODULE_PATH)[migration_name].Migration()

    return ALL_SPECIAL_MIGRATIONS[migration_name]


def get_special_migration_dependency(migration_name: str) -> Optional[str]:
    if TEST:
        return None

    return SPECIAL_MIGRATION_TO_DEPENDENCY[migration_name]
