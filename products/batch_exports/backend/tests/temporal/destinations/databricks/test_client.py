import os
import time
import asyncio
import threading

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from databricks.sql.exc import RequestError, ServerOperationError

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksClient,
    DatabricksConnectionError,
    DatabricksIncompatibleSchemaError,
    DatabricksOperationTimeoutError,
)

# Env vars required for the real-connection tests below. The _BE suffix avoids conflicts
# with env vars the Databricks SDK auto-discovers.
REAL_DATABRICKS_ENV_VARS = (
    "DATABRICKS_BE_SERVER_HOSTNAME",
    "DATABRICKS_BE_HTTP_PATH",
    "DATABRICKS_BE_CLIENT_ID",
    "DATABRICKS_BE_CLIENT_SECRET",
)

skip_without_real_databricks = pytest.mark.skipif(
    not all(env_var in os.environ for env_var in REAL_DATABRICKS_ENV_VARS),
    reason=f"Databricks required env vars are not set: {', '.join(REAL_DATABRICKS_ENV_VARS)}",
)


@pytest.fixture
def client() -> DatabricksClient:
    return DatabricksClient(
        server_hostname="test",
        http_path="test",
        client_id="test",
        client_secret="test",
        catalog="test",
        schema="test",
    )


@pytest.fixture
def mock_cursor(client: DatabricksClient) -> MagicMock:
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    connection = MagicMock()
    connection.cursor.return_value = cursor
    client._connection = connection
    return cursor


class TestExecuteQuery:
    @pytest.mark.parametrize("trigger", ["cancellation", "timeout"])
    async def test_cancels_cursor_on_cancellation_or_timeout(
        self, client: DatabricksClient, mock_cursor: MagicMock, trigger: str
    ):
        """Both task cancellation and per-call timeout should issue ``cursor.cancel()`` so the blocked
        worker thread running ``cursor.execute`` releases."""
        started_event = threading.Event()
        release_event = threading.Event()

        def blocking_execute(*_args, **_kwargs):
            started_event.set()
            release_event.wait(timeout=30)
            # Mirrors upstream SDK behavior: after cancel() is called, execute() raises RequestError.
            raise RequestError("query was cancelled")

        mock_cursor.execute.side_effect = blocking_execute
        mock_cursor.cancel.side_effect = lambda *_a, **_kw: release_event.set()

        if trigger == "cancellation":
            execute_task = asyncio.create_task(client.execute_query("SELECT 1", fetch_results=False))
            await asyncio.to_thread(started_event.wait, 5)
            execute_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await execute_task
        else:
            with pytest.raises(TimeoutError):
                await client.execute_query("SELECT 1", fetch_results=False, timeout=0.1)

        mock_cursor.cancel.assert_called_once()
        assert release_event.is_set()

    async def test_does_not_call_cancel_on_normal_completion(self, client: DatabricksClient, mock_cursor: MagicMock):
        """A successful query should not trigger a server-side cursor cancel."""
        mock_cursor.fetchall.return_value = []

        result = await client.execute_query("SELECT 1")

        assert result == []
        mock_cursor.execute.assert_called_once()
        mock_cursor.cancel.assert_not_called()

    async def test_propagates_genuine_request_error(self, client: DatabricksClient, mock_cursor: MagicMock):
        """A ``RequestError`` raised by ``cursor.execute`` (not from a cancel) should propagate
        unchanged, and we should not issue a redundant ``cursor.cancel()``."""
        mock_cursor.execute.side_effect = RequestError("transient failure")

        with pytest.raises(RequestError, match="transient failure"):
            await client.execute_query("SELECT 1", fetch_results=False)

        mock_cursor.cancel.assert_not_called()

    async def test_async_query_cancels_cursor_on_internal_timeout(
        self, client: DatabricksClient, mock_cursor: MagicMock
    ):
        """``execute_async_query``'s poll-loop timeout should also issue a ``cursor.cancel()``."""
        mock_cursor.is_query_pending.return_value = True

        with pytest.raises(TimeoutError, match="Timed out waiting for query"):
            await client.execute_async_query("SELECT 1", fetch_results=False, poll_interval=0.01, timeout=0.05)

        mock_cursor.cancel.assert_called_once()


class TestConnect:
    async def test_when_ping_times_out(self, client: DatabricksClient):
        """If the warehouse is asleep and doesn't resume within the ping timeout, ``connect()`` should
        raise ``DatabricksOperationTimeoutError`` before attempting ``use_catalog``."""
        use_catalog_mock = AsyncMock()

        with (
            patch.object(client, "_check_host_reachable", new=AsyncMock()),
            patch(
                "products.batch_exports.backend.temporal.destinations.databricks_batch_export.sql.connect",
                return_value=MagicMock(),
            ),
            patch.object(client, "execute_query", side_effect=TimeoutError("timed out")),
            patch.object(client, "use_catalog", new=use_catalog_mock),
        ):
            with pytest.raises(DatabricksOperationTimeoutError):
                async with client.connect():
                    pass

        use_catalog_mock.assert_not_called()

    async def test_when_invalid_host(self):
        """An invalid/unreachable host must fail fast rather than hang for ~5 minutes in the SDK's
        OIDC discovery (https://github.com/databricks/databricks-sdk-py/issues/1046).

        The TCP reachability preflight must fail the connection — using the configurable
        ``connect_timeout_seconds`` — *before* ``sql.connect`` is ever called, so no worker thread
        is left blocking on the hang-prone SDK call.
        """
        # 192.0.2.1 is reserved as non-routable (RFC 5737 TEST-NET-1), so the preflight connect fails
        # fast (no DNS, no real host).
        client = DatabricksClient(
            server_hostname="192.0.2.1",
            http_path="test",
            client_id="test",
            client_secret="test",
            catalog="test",
            schema="test",
            connect_timeout_seconds=0.01,
        )

        with patch(
            "products.batch_exports.backend.temporal.destinations.databricks_batch_export.sql.connect"
        ) as mock_sql_connect:
            with pytest.raises(
                DatabricksConnectionError,
                match="Failed to connect to Databricks. Please check that your connection details are valid.",
            ):
                async with client.connect():
                    pass

        mock_sql_connect.assert_not_called()


class TestQueryBuilders:
    async def test_merge_query_with_schema_evolution(self, client: DatabricksClient):
        merge_key = ["team_id", "distinct_id"]
        update_key = ["person_version", "person_distinct_id_version"]
        merge_query = client._get_merge_query_with_schema_evolution(
            target_table="test_target",
            source_table="test_source",
            merge_key=merge_key,
            update_key=update_key,
        )
        assert (
            merge_query
            == """
        MERGE WITH SCHEMA EVOLUTION INTO `test_target` AS target
        USING `test_source` AS source
        ON target.`team_id` = source.`team_id` AND target.`distinct_id` = source.`distinct_id`
        WHEN MATCHED AND (target.`person_version` < source.`person_version` OR target.`person_distinct_id_version` < source.`person_distinct_id_version`) THEN
            UPDATE SET *
        WHEN NOT MATCHED THEN
            INSERT *
        """
        )

    async def test_merge_query_without_schema_evolution(self, client: DatabricksClient):
        merge_key = ["team_id", "distinct_id"]
        update_key = ["person_version", "person_distinct_id_version"]
        merge_query = client._get_merge_query_without_schema_evolution(
            target_table="test_target",
            source_table="test_source",
            merge_key=merge_key,
            update_key=update_key,
            source_table_fields=[
                ("team_id", "INTEGER"),
                ("distinct_id", "STRING"),
                ("person_version", "INTEGER"),
                ("person_distinct_id_version", "INTEGER"),
                ("properties", "VARIANT"),
            ],
            target_table_field_names=[
                "team_id",
                "distinct_id",
                "person_version",
                "person_distinct_id_version",
                "properties",
            ],
        )
        assert (
            merge_query
            == """
        MERGE INTO `test_target` AS target
        USING `test_source` AS source
        ON target.`team_id` = source.`team_id` AND target.`distinct_id` = source.`distinct_id`
        WHEN MATCHED AND (target.`person_version` < source.`person_version` OR target.`person_distinct_id_version` < source.`person_distinct_id_version`) THEN
            UPDATE SET
                target.`team_id` = source.`team_id`, target.`distinct_id` = source.`distinct_id`, target.`person_version` = source.`person_version`, target.`person_distinct_id_version` = source.`person_distinct_id_version`, target.`properties` = source.`properties`
        WHEN NOT MATCHED THEN
            INSERT (`team_id`, `distinct_id`, `person_version`, `person_distinct_id_version`, `properties`)
            VALUES (source.`team_id`, source.`distinct_id`, source.`person_version`, source.`person_distinct_id_version`, source.`properties`)
        """
        )

    async def test_merge_query_without_schema_evolution_and_target_table_has_less_fields(
        self, client: DatabricksClient
    ):
        """Test that we construct the correct SQL for merging without schema evolution and the target table has less
        fields.

        In this example, the "new_field" field should be ignored.
        """
        merge_key = ["team_id", "distinct_id"]
        update_key = ["person_version", "person_distinct_id_version"]
        merge_query = client._get_merge_query_without_schema_evolution(
            target_table="test_target",
            source_table="test_source",
            merge_key=merge_key,
            update_key=update_key,
            source_table_fields=[
                ("team_id", "INTEGER"),
                ("distinct_id", "STRING"),
                ("person_version", "INTEGER"),
                ("person_distinct_id_version", "INTEGER"),
                ("properties", "VARIANT"),
                ("new_field", "STRING"),
            ],
            target_table_field_names=[
                "team_id",
                "distinct_id",
                "person_version",
                "person_distinct_id_version",
                "properties",
            ],
        )
        assert (
            merge_query
            == """
        MERGE INTO `test_target` AS target
        USING `test_source` AS source
        ON target.`team_id` = source.`team_id` AND target.`distinct_id` = source.`distinct_id`
        WHEN MATCHED AND (target.`person_version` < source.`person_version` OR target.`person_distinct_id_version` < source.`person_distinct_id_version`) THEN
            UPDATE SET
                target.`team_id` = source.`team_id`, target.`distinct_id` = source.`distinct_id`, target.`person_version` = source.`person_version`, target.`person_distinct_id_version` = source.`person_distinct_id_version`, target.`properties` = source.`properties`
        WHEN NOT MATCHED THEN
            INSERT (`team_id`, `distinct_id`, `person_version`, `person_distinct_id_version`, `properties`)
            VALUES (source.`team_id`, source.`distinct_id`, source.`person_version`, source.`person_distinct_id_version`, source.`properties`)
        """
        )

    async def test_copy_into_table_from_volume_query(self, client: DatabricksClient):
        """Test that we construct the correct SQL for COPY INTO from a volume, including VARIANT/BIGINT casts."""
        fields = [
            ("uuid", "STRING"),
            ("event", "STRING"),
            ("properties", "VARIANT"),
            ("distinct_id", "STRING"),
            ("team_id", "BIGINT"),
            ("timestamp", "TIMESTAMP"),
            ("databricks_ingested_timestamp", "TIMESTAMP"),
        ]
        query = client._get_copy_into_table_from_volume_query(
            table_name="test_table",
            volume_path="/Volumes/my_volume/path/file.parquet",
            fields=fields,
        )
        assert (
            query
            == """
        COPY INTO `test_table`
        FROM (
            SELECT `uuid`, `event`, PARSE_JSON(`properties`) as `properties`, `distinct_id`, CAST(`team_id` as BIGINT) as `team_id`, `timestamp`, `databricks_ingested_timestamp` FROM '/Volumes/my_volume/path/file.parquet'
        )
        FILEFORMAT = PARQUET
        COPY_OPTIONS ('force' = 'true', 'mergeSchema' = 'true')
        """
        )


class TestCopyIntoSchemaMismatch:
    MERGE_ERROR = "[DELTA_FAILED_TO_MERGE_FIELDS] Failed to merge fields 'properties' and 'properties'."

    async def test_remaps_merge_error_to_schema_mismatch(self, client: DatabricksClient):
        """The merge-fields error is remapped to a clear error reporting only the exported schema."""
        fields = [("properties", "STRING"), ("event", "STRING")]
        with patch.object(
            client, "execute_async_query", new=AsyncMock(side_effect=ServerOperationError(self.MERGE_ERROR))
        ):
            with pytest.raises(DatabricksIncompatibleSchemaError) as exc_info:
                await client.acopy_into_table_from_volume(
                    table_name="test_table", volume_path="/Volumes/x", fields=fields
                )

        message = str(exc_info.value)
        assert "Failed to merge fields" in message
        assert "Exported data schema: `properties` STRING, `event` STRING" in message
        # we must not disclose the destination table's schema (it could be any table the integration reaches)
        assert "Destination table schema" not in message

    async def test_non_merge_error_passes_through(self, client: DatabricksClient):
        """A non-merge ServerOperationError should still be handled by handle_common_errors."""
        with patch.object(
            client,
            "execute_async_query",
            new=AsyncMock(side_effect=ServerOperationError("Statement has timed out after 5 seconds")),
        ):
            with pytest.raises(DatabricksOperationTimeoutError):
                await client.acopy_into_table_from_volume(
                    table_name="test_table", volume_path="/Volumes/x", fields=[("properties", "STRING")]
                )


@skip_without_real_databricks
class TestRealDatabricksConnection:
    """Tests that exercise behavior against a real Databricks SQL warehouse.

    Skipped when ``DATABRICKS_BE_*`` env vars are missing.
    """

    # Databricks SQL doesn't have a native `sleep()` function, so we use an example from
    # https://github.com/databricks/databricks-sql-python/blob/cbd6a883f003f5f035db30705081208eb8af3de0/examples/query_cancel.py#L19-L21
    LONG_RUNNING_QUERY = (
        "SELECT SUM(A.id - B.id) FROM range(1000000000) A CROSS JOIN range(100000000) B GROUP BY (A.id - B.id)"
    )

    @staticmethod
    def _make_client(statement_timeout_seconds: float | None = None) -> DatabricksClient:
        return DatabricksClient(
            server_hostname=os.environ["DATABRICKS_BE_SERVER_HOSTNAME"],
            http_path=os.environ["DATABRICKS_BE_HTTP_PATH"],
            client_id=os.environ["DATABRICKS_BE_CLIENT_ID"],
            client_secret=os.environ["DATABRICKS_BE_CLIENT_SECRET"],
            catalog=os.getenv("DATABRICKS_CATALOG", "batch_export_tests"),
            schema="default",
            statement_timeout_seconds=statement_timeout_seconds,
        )

    async def test_execute_query_timeout_aborts_query_and_unblocks_worker_thread(self):
        """Tests that:
        1. ``execute_query``'s timeout actually fires and raises ``TimeoutError``.
        2. The worker thread running ``cursor.execute`` actually releases — this relies
           on databricks-sql-python's ``cursor.cancel()`` being called from another
           thread.
           See https://github.com/databricks/databricks-sql-python/blob/main/examples/query_cancel.py
        """
        client = self._make_client()

        started_at = time.monotonic()
        async with client.connect(set_context=False):
            with pytest.raises(TimeoutError):
                await client.execute_query(self.LONG_RUNNING_QUERY, fetch_results=False, timeout=1)
        elapsed = time.monotonic() - started_at

        # 1s timeout + cursor.cancel() RPC + thread teardown should land well under the SDK's
        # _retry_stop_after_attempts_duration ceiling. If we ever see this assertion fail it
        # almost certainly means cursor.cancel() didn't unblock the worker.
        assert elapsed < 30, f"execute_query took {elapsed:.1f}s after a 1s timeout — worker thread didn't release"

    async def test_server_side_statement_timeout_aborts_long_running_query(self):
        """
        Tests that setting ``statement_timeout_seconds`` works as expected, i.e.
        the server aborts queries exceeding the specified timeout.
        """
        client = self._make_client(statement_timeout_seconds=1)

        async with client.connect(set_context=False):
            with pytest.raises(ServerOperationError, match="Statement has timed out after 1 second"):
                await client.execute_query(self.LONG_RUNNING_QUERY, fetch_results=False)
