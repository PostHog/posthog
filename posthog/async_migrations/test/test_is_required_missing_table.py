import sys

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.async_migrations.setup import ALL_ASYNC_MIGRATIONS

# No pytest.mark.async_migrations here on purpose: the Core shards filter uses
# -m "not async_migrations", and this guards Django startup, so it must run there.

# These read a table's engine out of system.tables during `setup_async_migrations()`, which runs in
# AppConfig.ready(). If the table isn't there yet, an unguarded read used to raise (TypeError from a
# None engine, IndexError from an empty result set) and take the whole process down on first boot.
MIGRATIONS_READING_TABLE_ENGINES = [
    "0002_events_sample_by",
    "0004_replicated_schema",
    "0005_person_replacing_by_version",
]


class TestIsRequiredWithMissingTable(SimpleTestCase):
    @parameterized.expand(MIGRATIONS_READING_TABLE_ENGINES)
    def test_is_required_is_false_when_table_does_not_exist(self, migration_name: str) -> None:
        migration = ALL_ASYNC_MIGRATIONS[migration_name]

        # patch.object rather than patch(): the module paths start with a digit, which patch() rejects
        module = sys.modules[type(migration).__module__]

        with patch.object(module, "sync_execute", return_value=[]):
            self.assertFalse(migration.is_required())
