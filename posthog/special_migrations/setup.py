from infi.clickhouse_orm.utils import import_submodules

from posthog.settings import DEBUG

ALL_SPECIAL_MIGRATIONS = {}


def setup_special_migrations():
    for name, module in import_submodules("posthog.special_migrations.migrations").items():
        if name != "example" or DEBUG:
            ALL_SPECIAL_MIGRATIONS[name] = module.Migration()
