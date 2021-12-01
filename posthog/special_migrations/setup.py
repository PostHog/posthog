from django.core.exceptions import ImproperlyConfigured
from infi.clickhouse_orm.utils import import_submodules
from semantic_version.base import SimpleSpec, Version

from posthog.settings import DEBUG, TEST
from posthog.version import VERSION

ALL_SPECIAL_MIGRATIONS = {}

POSTHOG_VERSION = Version(VERSION)


def setup_special_migrations():
    from posthog.models.special_migration import SpecialMigration, get_all_completed_special_migrations

    if TEST:
        return

    all_migrations = import_submodules("posthog.special_migrations.migrations")

    if DEBUG:
        all_migrations["example"] = import_submodules("posthog.special_migrations.examples")["example"]

    for name, module in all_migrations.items():
        ALL_SPECIAL_MIGRATIONS[name] = module.Migration()

    applied_migrations = set(instance.name for instance in get_all_completed_special_migrations())
    unapplied_migrations = set(ALL_SPECIAL_MIGRATIONS.keys()) - applied_migrations

    print(unapplied_migrations)
    for migration_name in sorted(unapplied_migrations):
        migration = ALL_SPECIAL_MIGRATIONS[migration_name]
        if POSTHOG_VERSION > Version(migration.posthog_max_version):
            raise ImproperlyConfigured(f"Migration {migration_name} is required for PostHog versions above {VERSION}.")
        if POSTHOG_VERSION in SimpleSpec(f">={migration.posthog_min_version},<={migration.posthog_max_version}"):
            SpecialMigration.objects.get_or_create(name=migration_name, description=migration.description)
