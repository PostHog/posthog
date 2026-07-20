import pytest

from posthog.hogql.hogql import ast
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast

from posthog.sync import database_sync_to_async

from products.batch_exports.backend.hogql_source import UnsupportedHogQLQueryError
from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.record_batch_model import (
    HogQLQueryRecordBatchModel,
    SessionsRecordBatchModel,
    append_settings_to_query,
    resolve_batch_exports_model,
)

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

        assert hogql_query.where is not None
        assert isinstance(hogql_query.where, ast.And)
        assert team_id_filter in hogql_query.where.exprs

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
        printed_query, query_parameters = await model.as_insert_into_s3_query_with_parameters(
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            s3_folder="https://test-bucket.s3.amazonaws.com/test-prefix",
            s3_key="test-key",
            s3_secret="test-secret",
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

        # check that we have a date range set on the inner query using the session ID
        assert (
            "lessOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), plus("
            in printed_query
        )
        assert (
            "greaterOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), minus("
            in printed_query
        )

        # check that we have a log_comment set (we pass this in as a query parameter)
        assert "log_comment={log_comment}" in printed_query
        assert "log_comment" in query_parameters

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
            s3_key=None,
            s3_secret=None,
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
            s3_key="test-key",
            s3_secret="test-secret",
            num_partitions=5,
        )

        assert "INSERT INTO FUNCTION" in printed_query
        assert "https://test-bucket.s3.amazonaws.com/test-prefix/export_{{_partition_id}}.arrow" in printed_query
        assert "PARTITION BY rand() %% 5" in printed_query
        assert f"equals(events.team_id, {ateam.id})" in printed_query
        assert " SETTINGS " in printed_query
        assert "optimize_aggregation_in_order=1" in printed_query
        assert "max_bytes_before_external_sort=" in printed_query
        assert "max_bytes_before_external_group_by=" in printed_query
        assert "log_comment={log_comment}" in printed_query
        assert "log_comment" in query_parameters

    @pytest.mark.parametrize(
        "printed_query,expected_settings_count",
        [
            ("SELECT event FROM events", 1),
            # the printer merges table-required settings into the printed query; ours
            # must extend that clause, not open a second one
            ("SELECT event FROM some_table SETTINGS join_algorithm='hash'", 1),
            # a SETTINGS clause inside a subquery (e.g. a lazy table expansion) is not a
            # top-level clause: appending to it with a comma would be a syntax error
            ("SELECT event FROM (SELECT event FROM some_table SETTINGS join_algorithm='hash') AS sub", 2),
        ],
        ids=["without-settings", "with-trailing-settings", "with-subquery-settings"],
    )
    def test_append_settings_to_query(self, printed_query, expected_settings_count):
        result = append_settings_to_query(
            printed_query, ["optimize_aggregation_in_order=1", "log_comment={log_comment}"]
        )

        assert result.upper().count("SETTINGS") == expected_settings_count
        assert result.startswith(printed_query)
        assert "optimize_aggregation_in_order=1" in result
        assert "log_comment={log_comment}" in result

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
