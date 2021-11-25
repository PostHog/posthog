from django.core.exceptions import ImproperlyConfigured
from django.db.models.signals import post_init, post_save
from django.dispatch.dispatcher import receiver
from infi.clickhouse_orm.utils import import_submodules
from semantic_version.base import SimpleSpec, Version

from posthog.models.special_migration import SpecialMigration, get_all_completed_special_migrations
from posthog.settings import DEBUG
from posthog.version import VERSION

ALL_SPECIAL_MIGRATIONS = import_submodules("posthog.special_migrations.migrations")

if not DEBUG:
    del ALL_SPECIAL_MIGRATIONS["example"]


POSTHOG_VERSION = Version(VERSION)


def init_special_migrations():

    applied_migrations = set(instance.name for instance in get_all_completed_special_migrations())
    unapplied_migrations = set(ALL_SPECIAL_MIGRATIONS.keys()) - applied_migrations

    for migration_name in sorted(unapplied_migrations):
        migration = ALL_SPECIAL_MIGRATIONS[migration_name].Migration
        if POSTHOG_VERSION > Version(migration.posthog_max_version):
            raise ImproperlyConfigured(f"Migration {migration_name} is required for PostHog versions above {VERSION}.")

        if POSTHOG_VERSION in SimpleSpec(f">={migration.posthog_min_version},<={migration.posthog_max_version}"):
            SpecialMigration.objects.get_or_create(name=migration_name)
