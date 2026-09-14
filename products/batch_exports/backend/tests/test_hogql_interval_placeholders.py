import datetime as dt

import pytest
from unittest.mock import patch

from temporalio.testing import ActivityEnvironment

from posthog.hogql import ast

from products.batch_exports.backend.hogql_source import (
    UnsupportedHogQLQueryError,
    find_interval_placeholders,
    parse_hogql_select_for_batch_export,
    replace_interval_placeholders,
)
from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.utils.mock_clickhouse import MockClickHouseClient


@pytest.mark.parametrize("placeholder", ["data_interval_start", "data_interval_end"])
def test_referenced_bound_must_be_defined(placeholder: str) -> None:
    parsed = parse_hogql_select_for_batch_export(f"SELECT {{{placeholder}}} AS bound")
    supplied_bound = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    with pytest.raises(UnsupportedHogQLQueryError, match=f"'{placeholder}' is not defined"):
        replace_interval_placeholders(
            parsed,
            None if placeholder == "data_interval_start" else supplied_bound,
            None if placeholder == "data_interval_end" else supplied_bound,
        )


@pytest.mark.parametrize("with_end_placeholder", [False, True])
def test_missing_unreferenced_bounds_are_allowed(with_end_placeholder: bool) -> None:
    query = "SELECT {data_interval_end} AS bound" if with_end_placeholder else "SELECT 1 AS bound"
    parsed = parse_hogql_select_for_batch_export(query)
    end = dt.datetime(2026, 1, 1, tzinfo=dt.UTC) if with_end_placeholder else None

    replaced = replace_interval_placeholders(parsed, None, end)

    assert isinstance(replaced, ast.SelectQuery)
    assert isinstance(replaced.select[0], ast.Alias)
    assert isinstance(replaced.select[0].expr, ast.Constant)
    assert replaced.select[0].expr.value == (end if with_end_placeholder else 1)


def test_each_run_substitutes_its_own_bounds_without_mutating_the_query() -> None:
    parsed = parse_hogql_select_for_batch_export("SELECT {data_interval_start} AS start, {data_interval_end} AS end")
    first_start = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    for day in range(2):
        start = first_start + dt.timedelta(days=day)
        end = start + dt.timedelta(days=1)
        replaced = replace_interval_placeholders(parsed, start, end)

        assert isinstance(replaced, ast.SelectQuery)
        assert [
            expr.expr.value
            for expr in replaced.select
            if isinstance(expr, ast.Alias) and isinstance(expr.expr, ast.Constant)
        ] == [start, end]
        assert find_interval_placeholders(parsed) == {"data_interval_start", "data_interval_end"}


@pytest.mark.parametrize(
    "hogql_query,expected_error",
    [
        (
            "SELECT event FROM events WHERE timestamp >= {data_interval_start}",
            "'data_interval_start' is not defined",
        ),
        ("not a valid query", "Failed to parse HogQL query"),
        ("SELECT event FROM events WHERE timestamp >= {unknown}", "Unknown placeholder '{unknown}'"),
        (None, "no HogQL query was provided"),
    ],
    ids=["missing-start", "malformed-query", "unsupported-placeholder", "missing-query"],
)
async def test_invalid_hogql_returns_non_retryable_staging_error(hogql_query: str | None, expected_error: str) -> None:
    inputs = BatchExportInsertIntoInternalStageInputs(
        team_id=1,
        batch_export_id="00000000-0000-4000-8000-000000000001",
        data_interval_start=None,
        data_interval_end=(dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat(),
        batch_export_model=BatchExportModel(name="hogql", schema=None, hogql_query=hogql_query),
    )
    clickhouse = MockClickHouseClient()

    with patch(
        "products.batch_exports.backend.temporal.pipeline.internal_stage.get_client",
        return_value=clickhouse.mock_client_cm,
    ):
        result = await ActivityEnvironment().run(insert_into_internal_stage_activity, inputs)

    assert result.error is not None
    assert result.error.type == "UnsupportedHogQLQueryError"
    assert expected_error in result.error.message
    assert result.records_total is None
    clickhouse.expect_query_count(0)
