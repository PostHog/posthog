import importlib

import pytest
from unittest.mock import patch

from posthog.async_migrations.setup import get_async_migration_definition
from posthog.async_migrations.test.util import AsyncMigrationBaseTest

pytestmark = pytest.mark.async_migrations

MIGRATION_NAME = "0010_move_old_partitions"
migration_module = importlib.import_module(f"posthog.async_migrations.migrations.{MIGRATION_NAME}")


class Test0010MoveOldPartitions(AsyncMigrationBaseTest):
    def test_partition_parameters_are_bound_not_interpolated(self):
        migration = get_async_migration_definition(MIGRATION_NAME)
        malicious = "200001' OR '1'='1"

        with (
            patch.object(migration_module, "sync_execute", return_value=[]) as mock_sync_execute,
            patch.object(
                migration,
                "get_parameter",
                side_effect=lambda name: {
                    "OLDEST_PARTITION_TO_KEEP": malicious,
                    "NEWEST_PARTITION_TO_KEEP": "202308",
                }[name],
            ),
        ):
            migration._get_partitions_to_move()  # type: ignore[attr-defined]

        mock_sync_execute.assert_called_once()
        call = mock_sync_execute.call_args
        sql = call.args[0]
        params = call.args[1] if len(call.args) > 1 else call.kwargs.get("args")

        assert malicious not in sql
        assert params is not None
        assert malicious in params.values()
