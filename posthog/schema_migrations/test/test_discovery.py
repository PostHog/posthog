from unittest.mock import MagicMock, patch

from posthog.schema import NodeKind

import posthog.schema_migrations as schema_migrations_module
from posthog.schema_migrations import LATEST_VERSIONS, MIGRATIONS, _discover_migrations


def test_discover_migrations():
    with (
        patch("posthog.schema_migrations.os.listdir") as mock_listdir,
        patch("posthog.schema_migrations.importlib.import_module") as mock_import,
    ):
        # Mock migration files
        mock_listdir.return_value = ["0001_test.py", "0002_another.py", "not_a_migration.py"]

        # Mock migration modules
        mock_module1 = MagicMock()
        mock_module1.Migration.return_value.targets = {NodeKind.TRENDS_QUERY: 1}

        mock_module2 = MagicMock()
        mock_module2.Migration.return_value.targets = {NodeKind.TRENDS_QUERY: 2, NodeKind.FUNNELS_QUERY: 1}

        mock_import.side_effect = [mock_module1, mock_module2]

        # Reset state before test
        LATEST_VERSIONS.clear()
        MIGRATIONS.clear()
        schema_migrations_module._migrations_discovered = False

        # Run discovery
        _discover_migrations()

        # Verify correct files were imported
        assert mock_import.call_count == 2
        mock_import.assert_any_call("posthog.schema_migrations.0001_test")
        mock_import.assert_any_call("posthog.schema_migrations.0002_another")

        # Verify versions were updated correctly
        assert LATEST_VERSIONS[NodeKind.TRENDS_QUERY] == 3  # Max version + 1
        assert LATEST_VERSIONS[NodeKind.FUNNELS_QUERY] == 2  # Version + 1

        # Verify migrations were stored correctly
        assert NodeKind.TRENDS_QUERY in MIGRATIONS
        assert NodeKind.FUNNELS_QUERY in MIGRATIONS
        assert MIGRATIONS[NodeKind.TRENDS_QUERY][1] == mock_module1.Migration.return_value
        assert MIGRATIONS[NodeKind.TRENDS_QUERY][2] == mock_module2.Migration.return_value
        assert MIGRATIONS[NodeKind.FUNNELS_QUERY][1] == mock_module2.Migration.return_value
