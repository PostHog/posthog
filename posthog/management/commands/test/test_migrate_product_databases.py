from unittest import mock

from django.db import OperationalError
from django.test import SimpleTestCase

from posthog.management.commands.migrate_product_databases import ProductMigrationError, _migrate_app


class TestMigrateApp(SimpleTestCase):
    def _run(self, side_effect, *, max_retries=3):
        conn = mock.MagicMock(in_atomic_block=True)  # skip connection.close()
        with (
            mock.patch(
                "posthog.management.commands.migrate_product_databases.call_command", side_effect=side_effect
            ) as call,
            mock.patch("posthog.management.commands.migrate_product_databases.connections", {"alias": conn}),
            mock.patch(
                "posthog.management.commands.migrate_product_databases._next_unapplied_migration",
                return_value="0008_sourcebatch_superseded",
            ),
            mock.patch("posthog.management.commands.migrate_product_databases.time.sleep"),
        ):
            _migrate_app(
                mock.MagicMock(),
                "alias",
                "warehouse_sources_queue",
                max_retries=max_retries,
                retry_delay=0.0,
                backoff=2.0,
            )
        return call

    def test_retries_transient_lock_failure_then_succeeds(self):
        call = self._run([OperationalError("lock timeout"), OperationalError("deadlock detected"), None])
        assert call.call_count == 3

    def test_exhausted_retries_raise_with_migration_name(self):
        with self.assertRaises(ProductMigrationError) as ctx:
            self._run(OperationalError("lock timeout"), max_retries=2)

        err = ctx.exception
        assert err.app_label == "warehouse_sources_queue"
        assert err.migration_name == "0008_sourcebatch_superseded"
        assert "0008_sourcebatch_superseded" in str(err)

    def test_non_transient_error_is_not_retried(self):
        with self.assertRaises(ValueError):
            self._run(ValueError("bad migration"))
