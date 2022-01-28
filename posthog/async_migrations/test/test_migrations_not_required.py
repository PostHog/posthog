import pytest
from infi.clickhouse_orm.utils import import_submodules

from posthog.async_migrations.setup import ASYNC_MIGRATIONS_MODULE_PATH
from posthog.test.base import BaseTest


# Async migrations are data migrations aimed at getting users from an old schema to a new schema
# Fresh installs should have the new schema, however. So check that async migrations are being
# written correctly such that this is the case
class TestAsyncMigrationsNotRequired(BaseTest):
    @pytest.mark.ee
    def test_async_migrations_not_required_on_fresh_instances(self):
        modules = import_submodules(ASYNC_MIGRATIONS_MODULE_PATH)

        for module in modules.values():
            migration = module.Migration()
            is_migration_required = migration.is_required()

            self.assertFalse(is_migration_required)
