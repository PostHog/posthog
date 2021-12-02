from typing import Dict

from django.core.exceptions import ImproperlyConfigured
from infi.clickhouse_orm.utils import import_submodules
from semantic_version.base import Version

from posthog.settings import DEBUG, E2E_TESTING, SKIP_SERVICE_VERSION_REQUIREMENTS, TEST
from posthog.special_migrations.definition import SpecialMigrationDefinition
from posthog.utils import print_warning
from posthog.version import VERSION

ALL_SPECIAL_MIGRATIONS: Dict[str, SpecialMigrationDefinition] = {}

SPECIAL_MIGRATIONS_DEPENDENCY_MAP: Dict[str, str] = {}

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
    for migration_name, migration in ALL_SPECIAL_MIGRATIONS:

        SpecialMigration.objects.get_or_create(
            name=migration_name,
            description=migration.description,
            posthog_max_version=migration.posthog_max_version,
            posthog_max_version=migration.posthog_min_version,
        )

        dependency = migration.depends_on

        if not dependency:
            if first_migration:
                raise ImproperlyConfigured(
                    "Two or more special migrations have no dependency. Make sure only the first migration has no dependency."
                )

            first_migration = migration_name

        SPECIAL_MIGRATIONS_DEPENDENCY_MAP[migration_name] = dependency

        if migration_name in unapplied_migrations and POSTHOG_VERSION > Version(migration.posthog_max_version):
            raise ImproperlyConfigured(f"Migration {migration_name} is required for PostHog versions above {VERSION}.")
