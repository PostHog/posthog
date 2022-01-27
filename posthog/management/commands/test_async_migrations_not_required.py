import sys

from django.core.management.base import BaseCommand
from infi.clickhouse_orm.utils import import_submodules

from posthog.async_migrations.setup import ASYNC_MIGRATIONS_MODULE_PATH


class Command(BaseCommand):
    help = "Automated test to make sure async migrations are never required on fresh instances"

    def handle(self, *args, **options):
        modules = import_submodules(ASYNC_MIGRATIONS_MODULE_PATH)

        for name, module in modules.items():
            migration = module.Migration()
            is_migration_required = migration.is_required()

            if is_migration_required:
                print(
                    f"\n\n\033[91mAsync migration {name} is required on this instance. Is this a fresh instance? If so, something's wrong."
                )
                sys.exit(1)
