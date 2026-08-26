import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql.direct_sql.trino_adapter import TrinoAdapter, ensure_read_only_raw_trino_statement
from posthog.hogql.errors import ExposedHogQLError


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO events VALUES (1)",
        "DELETE FROM events",
        "CALL system.runtime.kill_query()",
        "SELECT 1; SELECT 2",
    ],
)
def test_raw_trino_queries_reject_non_read_only_sql(sql: str) -> None:
    with pytest.raises(ExposedHogQLError):
        ensure_read_only_raw_trino_statement(sql)


@pytest.mark.parametrize("sql", ["SELECT * FROM events", "WITH recent AS (SELECT 1) SELECT * FROM recent"])
def test_raw_trino_queries_accept_single_select(sql: str) -> None:
    assert ensure_read_only_raw_trino_statement(sql) == sql


def test_execute_returns_rows_and_types() -> None:
    adapter = TrinoAdapter()
    request = MagicMock()
    request.sql = "SELECT id, active FROM users"
    request.team.pk = 1
    request.source.id = "source-id"
    request.settings.max_execution_time = 30
    request.timings.measure.return_value.__enter__.return_value = None
    request.timings.measure.return_value.__exit__.return_value = None
    cursor = MagicMock()
    cursor.fetchmany.return_value = [(1, True)]
    cursor.description = [("id", "bigint"), ("active", "boolean")]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection

    with (
        patch.object(adapter, "validate_source_config", return_value=(MagicMock(), MagicMock())),
        patch(
            "products.warehouse_sources.backend.facade.source_management.connect_trino",
            return_value=connection_context,
        ),
    ):
        result = adapter.execute(request)

    cursor.execute.assert_called_once_with(request.sql)
    cursor.fetchmany.assert_called_once_with(1_000_001)
    assert result.results == [(1, True)]
    assert result.print_columns == ["id", "active"]
    assert result.types == [("id", "Nullable(Int64)"), ("active", "Nullable(Bool)")]
