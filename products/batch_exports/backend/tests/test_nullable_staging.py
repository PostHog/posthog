import datetime as dt
from collections.abc import Iterator

import pytest
import time_machine
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from temporalio.testing import ActivityEnvironment

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.models import Team

from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.errors import MissingRequiredInputsError
from products.batch_exports.backend.temporal.pipeline import internal_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import STAGE_NON_RETRYABLE_ERROR_TYPES
from products.batch_exports.backend.temporal.pipeline.query_ranges import is_5_min_batch_export
from products.batch_exports.backend.temporal.record_batch_model import (
    HogQLQueryRecordBatchModel,
    SessionsRecordBatchModel,
)

START = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
END = START + dt.timedelta(minutes=5)
EXPORT_ID = "00000000-0000-4000-8000-000000000001"
RUN_ID = "00000000-0000-4000-8000-000000000002"


@pytest.fixture
def staging_clients() -> Iterator[tuple[AsyncMock, AsyncMock]]:
    clickhouse = AsyncMock()
    clickhouse.execute_query_with_summary.return_value = {"written_rows": "1"}
    clickhouse_cm = MagicMock()
    clickhouse_cm.__aenter__.return_value = clickhouse
    s3 = AsyncMock()
    s3.list_objects_v2.return_value = {}
    s3_cm = MagicMock()
    s3_cm.__aenter__.return_value = s3
    with (
        patch.object(internal_stage, "get_client", return_value=clickhouse_cm),
        patch.object(internal_stage, "get_s3_client", return_value=s3_cm),
        patch("products.batch_exports.backend.temporal.utils.aupdate_batch_export_run", new_callable=AsyncMock),
        patch.object(
            HogQLQueryRecordBatchModel,
            "get_hogql_context",
            new_callable=AsyncMock,
            side_effect=lambda: HogQLContext(
                team=Team(id=1),
                database=Database(),
                restricted_properties=set(),
                apply_events_retention_floor=False,
                enable_select_queries=True,
                values={"log_comment": "{}"},
            ),
        ),
    ):
        yield clickhouse, s3


@pytest.mark.asyncio
@pytest.mark.parametrize("start,end", [(None, None), (START, None), (None, END), (START, END)])
async def test_hogql_staging_preserves_optional_bounds_and_cleanup_namespace(
    staging_clients: tuple[AsyncMock, AsyncMock], start: dt.datetime | None, end: dt.datetime | None
) -> None:
    clickhouse, s3 = staging_clients
    start_str = start.isoformat() if start is not None else None
    end_str = end.isoformat() if end is not None else None
    inputs = internal_stage.BatchExportInsertIntoInternalStageInputs(
        team_id=1,
        batch_export_id=EXPORT_ID,
        run_id=RUN_ID,
        data_interval_start=start_str,
        data_interval_end=end_str,
        on_demand=True,
        batch_export_model=BatchExportModel(name="hogql", schema=None, hogql_query="SELECT 1 AS value"),
    )

    result = await ActivityEnvironment().run(internal_stage.insert_into_internal_stage_activity, inputs)

    expected_base = (
        f"batch-exports/{EXPORT_ID}/runs/{RUN_ID}"
        if start is None or end is None
        else f"batch-exports/{EXPORT_ID}/{start_str}-{end_str}"
    )
    assert result.error is None
    assert result.records_total == 1
    assert result.stage_folder == f"{expected_base}/attempt_1"
    assert s3.list_objects_v2.call_args.kwargs["Prefix"] == expected_base
    query = clickhouse.execute_query_with_summary.call_args.args[0]
    assert result.stage_folder in query
    assert "SELECT" in query
    query_parameters = clickhouse.execute_query_with_summary.call_args.kwargs["query_parameters"]
    assert "interval_start" not in query_parameters
    assert "interval_end" not in query_parameters


@pytest.mark.asyncio
@pytest.mark.parametrize("hogql_query", [None, "SELECT {data_interval_end} AS value"])
async def test_unsupported_hogql_returns_nonretryable_staging_error(
    staging_clients: tuple[AsyncMock, AsyncMock], hogql_query: str | None
) -> None:
    inputs = internal_stage.BatchExportInsertIntoInternalStageInputs(
        team_id=1,
        batch_export_id=EXPORT_ID,
        run_id=RUN_ID,
        data_interval_start=None,
        data_interval_end=None,
        on_demand=True,
        batch_export_model=BatchExportModel(name="hogql", schema=None, hogql_query=hogql_query),
    )

    result = await ActivityEnvironment().run(internal_stage.insert_into_internal_stage_activity, inputs)

    assert result.error is not None
    assert result.error.type == "UnsupportedHogQLQueryError"
    staging_clients[0].execute_query_with_summary.assert_not_called()
    staging_clients[1].list_objects_v2.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end,bound",
    [
        (END, None, "data_interval_start"),
        (None, END, "data_interval_end"),
    ],
)
async def test_hogql_staging_rejects_each_future_bound_without_waiting(
    staging_clients: tuple[AsyncMock, AsyncMock],
    start: dt.datetime | None,
    end: dt.datetime | None,
    bound: str,
) -> None:
    inputs = internal_stage.BatchExportInsertIntoInternalStageInputs(
        team_id=1,
        batch_export_id=EXPORT_ID,
        run_id=RUN_ID,
        data_interval_start=start.isoformat() if start is not None else None,
        data_interval_end=end.isoformat() if end is not None else None,
        on_demand=True,
        batch_export_model=BatchExportModel(name="hogql", schema=None, hogql_query="SELECT 1 AS value"),
    )
    # Patch the helper rather than override settings.TEST, because DatabaseSyncToAsync calls
    # close_old_connections() whenever settings.TEST is False, and that needs a database.
    with (
        time_machine.travel(START, tick=False),
        patch.object(internal_stage, "_is_local_dev_or_test", return_value=False),
    ):
        result = await ActivityEnvironment().run(internal_stage.insert_into_internal_stage_activity, inputs)

    assert result.error is not None
    assert result.error.type == "DataIntervalInFutureError"
    assert f"'{bound}'" in result.error.message
    assert END.isoformat() in result.error.message
    staging_clients[0].is_alive.assert_not_called()
    staging_clients[1].list_objects_v2.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "on_demand,model_name,run_id",
    [(False, "hogql", RUN_ID), (True, "hogql", None), (True, "events", RUN_ID)],
    ids=["scheduled-missing-end", "on-demand-missing-run-id", "fixed-model-missing-end"],
)
async def test_missing_staging_inputs_raise(
    staging_clients: tuple[AsyncMock, AsyncMock],
    on_demand: bool,
    model_name: str,
    run_id: str | None,
) -> None:
    inputs = internal_stage.BatchExportInsertIntoInternalStageInputs(
        team_id=1,
        batch_export_id=EXPORT_ID,
        run_id=run_id,
        data_interval_start=None,
        data_interval_end=None,
        on_demand=on_demand,
        batch_export_model=BatchExportModel(name=model_name, schema=None, hogql_query="SELECT 1 AS value"),
    )
    with pytest.raises(MissingRequiredInputsError, match="require"):
        await ActivityEnvironment().run(internal_stage.insert_into_internal_stage_activity, inputs)
    assert "MissingRequiredInputsError" not in STAGE_NON_RETRYABLE_ERROR_TYPES
    staging_clients[0].is_alive.assert_not_called()
    staging_clients[1].list_objects_v2.assert_not_called()


@pytest.mark.parametrize("is_backfill", [False, True])
def test_sessions_require_an_interval_end(is_backfill: bool) -> None:
    with pytest.raises(MissingRequiredInputsError, match="requires data_interval_end"):
        SessionsRecordBatchModel(team_id=1, is_backfill=is_backfill).get_hogql_query(START, None)


@pytest.mark.asyncio
async def test_raw_sql_staging_requires_an_interval_end() -> None:
    with pytest.raises(MissingRequiredInputsError, match="require data_interval_end"):
        await internal_stage._write_batch_export_record_batches_to_internal_stage(
            query_or_model="SELECT 1",
            full_range=(None, None),
            query_parameters={},
            team_id=1,
            batch_export_id=EXPORT_ID,
            data_interval_start=None,
            data_interval_end=None,
            s3_staging_folder_url="https://example.com/stage",
            run_id=RUN_ID,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("start", [None, START])
async def test_partition_count_without_end_uses_static_default(start: dt.datetime | None) -> None:
    with override_settings(BATCH_EXPORT_DYNAMIC_PARTITIONING_ENABLED=True, BATCH_EXPORT_CLICKHOUSE_S3_PARTITIONS=7):
        assert await internal_stage.compute_num_partitions(EXPORT_ID, start, None) == 7


@pytest.mark.parametrize(
    "start,end,expected",
    [(None, None, False), (START, None, False), (None, END, False), (START, END, True)],
)
def test_five_minute_detection_requires_both_bounds(
    start: dt.datetime | None, end: dt.datetime | None, expected: bool
) -> None:
    assert is_5_min_batch_export((start, end)) is expected
