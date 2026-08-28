import datetime as dt

import pytest

from django.test import override_settings

from posthog.hogql.hogql import ast
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast

from posthog.credentials import AWSKeyPair
from posthog.models.utils import uuid7
from posthog.sync import database_sync_to_async
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.hogql_source import UnsupportedHogQLQueryError
from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.record_batch_model import (
    HogQLQueryRecordBatchModel,
    SessionsRecordBatchModel,
    resolve_batch_exports_model,
)
from products.batch_exports.backend.temporal.sql.sessions import SESSIONS_LOOKBACK_DAYS
from products.batch_exports.backend.tests.temporal.utils.clickhouse import truncate_events, truncate_sessions

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class TestSessionsRecordBatchModel:
    async def test_get_hogql_query(self, ateam, data_interval_start, data_interval_end):
        model = SessionsRecordBatchModel(
            team_id=ateam.id,
        )
        hogql_query = model.get_hogql_query(data_interval_start, data_interval_end)
        team_id_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["sessions", "team_id"]),
            right=ast.Constant(value=ateam.id),
        )
        # the $end_timestamp lower bound is what lets hogql prune raw_sessions partitions,
        # shifted back to still catch sessions ingested up to SESSIONS_MAX_LATENESS late
        lateness_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["$end_timestamp"]),
            right=ast.Constant(value=data_interval_start - SESSIONS_LOOKBACK_DAYS),
        )

        assert hogql_query.where is not None
        assert isinstance(hogql_query.where, ast.And)
        assert team_id_filter in hogql_query.where.exprs
        assert lateness_filter in hogql_query.where.exprs

    async def test_get_hogql_query_for_backfill(self, ateam, data_interval_start, data_interval_end):
        """Backfill runs select sessions by event time ($end_timestamp), not by the
        _inserted_at watermark, so sessions ingested beyond SESSIONS_MAX_LATENESS can
        still be exported by backfilling their $end_timestamp range."""
        model = SessionsRecordBatchModel(team_id=ateam.id, is_backfill=True)
        hogql_query = model.get_hogql_query(data_interval_start, data_interval_end)

        lower_bound = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["$end_timestamp"]),
            right=ast.Constant(value=data_interval_start),
        )
        upper_bound = ast.CompareOperation(
            op=ast.CompareOperationOp.Lt,
            left=ast.Field(chain=["$end_timestamp"]),
            right=ast.Constant(value=data_interval_end),
        )

        assert hogql_query.where is not None
        assert isinstance(hogql_query.where, ast.And)
        assert lower_bound in hogql_query.where.exprs
        assert upper_bound in hogql_query.where.exprs
        # no _inserted_at bounds: backfill selection is purely by event time
        assert not any(
            isinstance(expr, ast.CompareOperation)
            and isinstance(expr.left, ast.Field)
            and expr.left.chain == ["_inserted_at"]
            for expr in hogql_query.where.exprs
        )

    async def test_as_query_with_parameters(self, ateam, data_interval_start, data_interval_end):
        model = SessionsRecordBatchModel(
            team_id=ateam.id,
        )
        printed_query, _ = await model.as_query_with_parameters(data_interval_start, data_interval_end)

        assert f"equals(raw_sessions.team_id, {ateam.id})" in printed_query
        assert "FORMAT ArrowStream" in printed_query
        assert (
            f"greaterOrEquals(_inserted_at, toDateTime64('{data_interval_start:%Y-%m-%d %H:%M:%S.%f}', 6, 'UTC')"
            in printed_query
        )
        assert f"less(_inserted_at, toDateTime64('{data_interval_end:%Y-%m-%d %H:%M:%S.%f}', 6, 'UTC')" in printed_query
        # the $end_timestamp lower bound is shifted back by lookback days
        assert (
            f"toDateTime64('{data_interval_start - SESSIONS_LOOKBACK_DAYS:%Y-%m-%d %H:%M:%S.%f}', 6, 'UTC')"
            in printed_query
        )

        # check that we have a date range set on the inner query using the session ID
        assert (
            "lessOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), plus("
            in printed_query
        )
        assert (
            "greaterOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), minus("
            in printed_query
        )

    async def test_get_hogql_query_returns_independent_ast_per_call(
        self, ateam, another_ateam, data_interval_start, data_interval_end
    ):
        """get_hogql_query must return an independent AST each time, not a shared mutable reference."""
        model_a = SessionsRecordBatchModel(team_id=ateam.id)
        model_b = SessionsRecordBatchModel(team_id=another_ateam.id)

        query_a = model_a.get_hogql_query(data_interval_start, data_interval_end)
        query_b = model_b.get_hogql_query(data_interval_start, data_interval_end)

        assert query_a is not query_b

    async def test_interleaved_calls_do_not_mix_team_ids(
        self, ateam, another_ateam, data_interval_start, data_interval_end
    ):
        """Regression test to reproduce a previous race condition in as_query_with_parameters where
        two different models were created with different team IDs, and the second model's query
        overwrote the first model's query."""

        model_a = SessionsRecordBatchModel(team_id=ateam.id)
        model_b = SessionsRecordBatchModel(team_id=another_ateam.id)

        # Task A: get_hogql_query sets .where with team A's filter
        hogql_query_a = model_a.get_hogql_query(data_interval_start, data_interval_end)
        # Task A: awaits get_hogql_context (yields control)
        context_a = await model_a.get_hogql_context()
        # Task B runs during the yield and overwrites .where with team B's filter
        model_b.get_hogql_query(data_interval_start, data_interval_end)
        # Task A resumes and prints the query — hogql_query_a is a ref to the shared object
        prepared = await database_sync_to_async(prepare_ast_for_printing)(
            hogql_query_a, context=context_a, dialect="clickhouse", stack=[]
        )
        assert prepared is not None
        context_a.output_format = "ArrowStream"
        printed_query = print_prepared_ast(prepared, context=context_a, dialect="clickhouse", stack=[])

        assert f"equals(raw_sessions.team_id, {ateam.id})" in printed_query
        assert f"team_id, {another_ateam.id}" not in printed_query

    async def test_as_insert_into_s3_query_with_parameters(self, ateam, data_interval_start, data_interval_end):
        model = SessionsRecordBatchModel(
            team_id=ateam.id,
        )
        printed_query, _ = await model.as_insert_into_s3_query_with_parameters(
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            s3_folder="https://test-bucket.s3.amazonaws.com/test-prefix",
            credentials=AWSKeyPair.unsafe_from_strings("test-key", "test-secret"),
            num_partitions=5,
        )

        assert "INSERT INTO FUNCTION" in printed_query
        # parition_id is a ClickHouse variable, so we need to escape it
        assert "https://test-bucket.s3.amazonaws.com/test-prefix/export_{{_partition_id}}.arrow" in printed_query
        assert "PARTITION BY rand() %% 5" in printed_query
        assert f"equals(raw_sessions.team_id, {ateam.id})" in printed_query
        assert (
            f"greaterOrEquals(_inserted_at, toDateTime64('{data_interval_start:%Y-%m-%d %H:%M:%S.%f}', 6, 'UTC')"
            in printed_query
        )
        assert f"less(_inserted_at, toDateTime64('{data_interval_end:%Y-%m-%d %H:%M:%S.%f}', 6, 'UTC')" in printed_query
        # the $end_timestamp lower bound is shifted back by the lateness horizon
        assert (
            f"toDateTime64('{data_interval_start - SESSIONS_LOOKBACK_DAYS:%Y-%m-%d %H:%M:%S.%f}', 6, 'UTC')"
            in printed_query
        )

        # check that we have a date range set on the inner query using the session ID
        assert (
            "lessOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), plus("
            in printed_query
        )
        assert (
            "greaterOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), minus("
            in printed_query
        )
        # the sessions query carries its settings on the AST, so the printer renders them
        assert "SETTINGS" in printed_query
        assert "optimize_aggregation_in_order=1" in printed_query
        # this model needs no request settings: the printer already emitted them
        assert model.get_clickhouse_request_settings() == {}

    async def test_as_insert_into_s3_query_with_parameters_keyless_auth(
        self, ateam, data_interval_start, data_interval_end
    ):
        """Test that keyless S3 auth generates the correct s3() function call without credentials."""
        model = SessionsRecordBatchModel(
            team_id=ateam.id,
        )
        printed_query, _ = await model.as_insert_into_s3_query_with_parameters(
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            s3_folder="https://test-bucket.s3.amazonaws.com/test-prefix",
            credentials=None,
            num_partitions=5,
        )

        assert "INSERT INTO FUNCTION" in printed_query
        assert "https://test-bucket.s3.amazonaws.com/test-prefix/export_{{_partition_id}}.arrow" in printed_query
        # For keyless auth, the s3() call should only have 2 parameters (url, format), not 4
        assert (
            "s3('https://test-bucket.s3.amazonaws.com/test-prefix/export_{{_partition_id}}.arrow', 'ArrowStream')"
            in printed_query
        )
        assert "PARTITION BY rand() %% 5" in printed_query


class TestSessionsRecordBatchModelSelection:
    """Run the sessions model query against ClickHouse to verify which intervals select a session."""

    @pytest.fixture(autouse=True)
    async def truncate_tables(self, clickhouse_client):
        await truncate_events(clickhouse_client)
        await truncate_sessions(clickhouse_client)

    async def _generate_session(
        self,
        clickhouse_client,
        team_id: int,
        event_time: dt.datetime,
        inserted_at: dt.datetime,
    ) -> str:
        session_id = str(uuid7(unix_ms_time=int(event_time.timestamp() * 1000)))
        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=team_id,
            start_time=event_time,
            end_time=event_time + dt.timedelta(minutes=2),
            count=1,
            count_outside_range=0,
            count_other_team=0,
            inserted_at=inserted_at,
            table="sharded_events",
            event_name="test-event",
            properties={"$session_id": session_id},
            insert_sessions=True,
        )
        return session_id

    async def _select_session_ids(
        self,
        clickhouse_client,
        model: SessionsRecordBatchModel,
        interval_start: dt.datetime,
        interval_end: dt.datetime,
    ) -> list[str]:
        printed_query, parameters = await model._print_query(interval_start, interval_end, output_format="JSONEachRow")
        rows = await clickhouse_client.read_query_as_jsonl(printed_query, query_parameters=parameters)
        return [row["session_id"] for row in rows]

    async def test_selects_late_session_by_interval_covering_its_ingestion(self, clickhouse_client, ateam):
        """A session whose events are ingested late (within SESSIONS_LOOKBACK_DAYS) is selected
        by the interval covering its ingestion time, not the one covering its event timestamps."""
        event_time = dt.datetime(2021, 1, 18, 12, 0, 0, tzinfo=dt.UTC)
        ingested_at = dt.datetime(2021, 1, 20, 6, 30, 0, tzinfo=dt.UTC)
        session_id = await self._generate_session(clickhouse_client, ateam.pk, event_time, ingested_at)
        model = SessionsRecordBatchModel(team_id=ateam.pk)

        selected_by_event_interval = await self._select_session_ids(
            clickhouse_client,
            model,
            dt.datetime(2021, 1, 18, 12, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 18, 13, 0, 0, tzinfo=dt.UTC),
        )
        selected_by_ingestion_interval = await self._select_session_ids(
            clickhouse_client,
            model,
            dt.datetime(2021, 1, 20, 6, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 20, 7, 0, 0, tzinfo=dt.UTC),
        )

        assert selected_by_event_interval == []
        assert selected_by_ingestion_interval == [session_id]

    async def test_session_ingested_beyond_lateness_horizon_requires_backfill(self, clickhouse_client, ateam):
        """A session ingested more than SESSIONS_LOOKBACK_DAYS after it ended is skipped by
        incremental runs (the prunable $end_timestamp bound excludes it), but a backfill of
        its event-time range picks it up."""
        event_time = dt.datetime(2021, 1, 10, 12, 0, 0, tzinfo=dt.UTC)
        ingested_at = dt.datetime(2021, 1, 20, 6, 30, 0, tzinfo=dt.UTC)
        session_id = await self._generate_session(clickhouse_client, ateam.pk, event_time, ingested_at)

        incremental_model = SessionsRecordBatchModel(team_id=ateam.pk)
        selected_by_ingestion_interval = await self._select_session_ids(
            clickhouse_client,
            incremental_model,
            dt.datetime(2021, 1, 20, 6, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 20, 7, 0, 0, tzinfo=dt.UTC),
        )

        backfill_model = SessionsRecordBatchModel(team_id=ateam.pk, is_backfill=True)
        selected_by_backfill_of_event_range = await self._select_session_ids(
            clickhouse_client,
            backfill_model,
            dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 11, 0, 0, 0, tzinfo=dt.UTC),
        )

        assert selected_by_ingestion_interval == []
        assert selected_by_backfill_of_event_range == [session_id]

    async def test_sessions_without_max_inserted_at_fall_back_to_end_timestamp(self, clickhouse_client, ateam):
        """Sessions from before raw_sessions had max_inserted_at carry the epoch value; the
        watermark falls back to $end_timestamp, so they are still selected by their event-time
        interval."""
        event_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        epoch = dt.datetime(1970, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
        session_id = await self._generate_session(clickhouse_client, ateam.pk, event_time, epoch)
        model = SessionsRecordBatchModel(team_id=ateam.pk)

        selected = await self._select_session_ids(
            clickhouse_client,
            model,
            dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 15, 11, 0, 0, tzinfo=dt.UTC),
        )

        assert selected == [session_id]


class TestHogQLQueryRecordBatchModel:
    async def test_as_query_with_parameters(self, ateam, data_interval_start, data_interval_end):
        model = HogQLQueryRecordBatchModel(
            team_id=ateam.id, hogql_query="SELECT event AS event, distinct_id AS distinct_id FROM events"
        )
        printed_query, query_parameters = await model.as_query_with_parameters(data_interval_start, data_interval_end)

        # should add filter on team_id
        assert f"equals(events.team_id, {ateam.id})" in printed_query
        assert "FORMAT ArrowStream" in printed_query
        assert "log_comment" in query_parameters

    async def test_as_insert_into_s3_query_with_parameters(self, ateam, data_interval_start, data_interval_end):
        model = HogQLQueryRecordBatchModel(
            team_id=ateam.id, hogql_query="SELECT event AS event, distinct_id AS distinct_id FROM events"
        )
        printed_query, query_parameters = await model.as_insert_into_s3_query_with_parameters(
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            s3_folder="https://test-bucket.s3.amazonaws.com/test-prefix",
            credentials=AWSKeyPair.unsafe_from_strings("test-key", "test-secret"),
            num_partitions=5,
        )

        assert "INSERT INTO FUNCTION" in printed_query
        assert "https://test-bucket.s3.amazonaws.com/test-prefix/export_{{_partition_id}}.arrow" in printed_query
        assert "PARTITION BY rand() %% 5" in printed_query
        assert f"equals(events.team_id, {ateam.id})" in printed_query
        # the user's query is wrapped as-is: settings are sent as query parameters, so we never write a
        # SETTINGS clause into the query
        assert "SETTINGS" not in printed_query

    @override_settings(
        BATCH_EXPORT_HOGQL_MAX_EXECUTION_TIME=900,
        BATCH_EXPORT_HOGQL_MAX_MEMORY_USAGE=30_000_000_000,
        BATCH_EXPORT_HOGQL_MAX_BYTES_TO_READ=200_000_000_000,
    )
    async def test_get_clickhouse_request_settings(self):
        """Batch export settings are sent as query parameters rather than a SETTINGS clause.

        Values are rendered the way the HogQL printer renders them (bools as 1/0), so a setting
        reads the same in query_log however it was applied. ClickHouse rejects unknown setting names
        outright, so a typo here fails the export. The per-query resource limits are read from Django
        settings at call time, hence the `override_settings` above pins them for the assertion.

        `read_overflow_mode`/`timeout_overflow_mode` are `throw` on purpose: without them a query
        that hits the time or read limit could return a truncated result as a success. The spill
        thresholds are half the memory cap, and the `max_bytes_ratio_before_external_*` settings are
        0 so that those thresholds are what ClickHouse actually spills on.
        """
        model = HogQLQueryRecordBatchModel(team_id=1, hogql_query="SELECT event AS event FROM events")

        assert model.get_clickhouse_request_settings() == {
            "optimize_aggregation_in_order": "1",
            "max_bytes_before_external_sort": "15000000000",
            "max_bytes_before_external_group_by": "15000000000",
            "max_bytes_ratio_before_external_sort": "0.0",
            "max_bytes_ratio_before_external_group_by": "0.0",
            "max_execution_time": "900",
            "max_memory_usage": "30000000000",
            "max_bytes_to_read": "200000000000",
            "read_overflow_mode": "throw",
            "timeout_overflow_mode": "throw",
        }

    @pytest.mark.parametrize(
        "hogql_query,expected_message",
        [
            ("SELECT event AS event FROM events WHERE {filters}", "Placeholders are not supported"),
            ("SELECT event AS event FROM events WHERE event = {placeholder_field}", "Placeholders are not supported"),
            ("SELECT event AS event FROM events WHERE event = {concat('a', 'b')}", "Placeholders are not supported"),
            ("not a valid query", "Failed to parse HogQL query"),
            ("DROP TABLE events", "Failed to parse HogQL query"),
        ],
        ids=["filters", "placeholder-field", "placeholder-expression", "invalid-syntax", "not-a-select"],
    )
    async def test_get_hogql_query_raises_on_unsupported_query(
        self, hogql_query, expected_message, data_interval_start, data_interval_end
    ):
        model = HogQLQueryRecordBatchModel(team_id=1, hogql_query=hogql_query)

        with pytest.raises(UnsupportedHogQLQueryError, match=expected_message):
            model.get_hogql_query(data_interval_start, data_interval_end)

    @pytest.mark.parametrize(
        "hogql_query",
        [
            "SELECT event AS event FROM events SETTINGS max_bytes_to_read=0",
            "SELECT event AS event FROM events UNION ALL SELECT event AS event FROM events SETTINGS max_bytes_to_read=0",
            "WITH x AS (SELECT event FROM events SETTINGS max_bytes_to_read=0) SELECT event AS event FROM x",
        ],
        ids=["top-level", "after-union", "in-cte"],
    )
    async def test_get_hogql_query_rejects_a_settings_clause(self, hogql_query, data_interval_start, data_interval_end):
        """A user query carrying its own SETTINGS is rejected, wherever that clause appears.

        The per-query resource limits are sent as request settings, and a query-level SETTINGS clause
        takes precedence over those, so a query able to smuggle one through could lift its own memory,
        time and bytes-read caps. The parser refusing these is what the limits rest on, and nothing
        else asserts it.
        """
        model = HogQLQueryRecordBatchModel(team_id=1, hogql_query=hogql_query)

        with pytest.raises(UnsupportedHogQLQueryError, match="settingsClause"):
            model.get_hogql_query(data_interval_start, data_interval_end)

    async def test_resolve_batch_exports_model_returns_hogql_model(self):
        batch_export_model = BatchExportModel(
            name="hogql", schema=None, hogql_query="SELECT event AS event FROM events"
        )

        _, record_batch_model, model_name, _, _, _ = resolve_batch_exports_model(
            team_id=1, batch_export_model=batch_export_model
        )

        assert isinstance(record_batch_model, HogQLQueryRecordBatchModel)
        assert model_name == "hogql"
        assert record_batch_model.hogql_query == batch_export_model.hogql_query

    async def test_resolve_batch_exports_model_raises_without_hogql_query(self):
        """Without this, a missing query would fall through to the events template path and export the wrong data."""
        with pytest.raises(UnsupportedHogQLQueryError):
            resolve_batch_exports_model(team_id=1, batch_export_model=BatchExportModel(name="hogql", schema=None))
