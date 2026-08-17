from unittest.mock import MagicMock, patch

from posthog.async_migrations.setup import _is_migration_required, setup_async_migrations
from posthog.async_migrations.test.util import AsyncMigrationBaseTest


class TestSetupAsyncMigrations(AsyncMigrationBaseTest):
    def test_is_migration_required_swallows_connectivity_errors(self):
        migration = MagicMock()
        migration.is_required.side_effect = ConnectionError("Authentication required")

        with patch("posthog.async_migrations.setup.capture_exception") as mock_capture:
            self.assertFalse(_is_migration_required("0005_test", migration))

        mock_capture.assert_called_once()

    def test_setup_does_not_raise_when_is_required_fails(self):
        # A superseded migration whose readiness probe cannot reach Redis or ClickHouse must not
        # stop app startup. This guards the process boot that celery beat and worker depend on.
        migration = MagicMock()
        migration.description = "test migration"
        migration.posthog_min_version = "1.38.0"
        migration.posthog_max_version = "1.41.99"
        migration.depends_on = None
        migration.is_required.side_effect = ConnectionError("Authentication required")

        with (
            patch.dict("posthog.async_migrations.setup.ALL_ASYNC_MIGRATIONS", {"0005_test": migration}, clear=True),
            patch.dict("posthog.async_migrations.setup.ASYNC_MIGRATION_TO_DEPENDENCY", {}, clear=True),
            patch.dict("posthog.async_migrations.setup.DEPENDENCY_TO_ASYNC_MIGRATION", {}, clear=True),
        ):
            setup_async_migrations()
