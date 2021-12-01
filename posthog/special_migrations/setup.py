from infi.clickhouse_orm.utils import import_submodules

from posthog.settings import DEBUG

ALL_SPECIAL_MIGRATIONS = {}


def setup_special_migrations():
    all_migrations = import_submodules("posthog.special_migrations.migrations")

    if DEBUG:
        all_migrations["example"] = import_submodules("posthog.special_migrations.examples")["example"]

    for name, module in all_migrations.items():
        ALL_SPECIAL_MIGRATIONS[name] = module.Migration()
