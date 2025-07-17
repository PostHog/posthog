import pytest

from posthog.hogql.hogql import ast
from products.batch_exports.backend.temporal.record_batch_model import (
    SessionsRecordBatchModel,
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

    async def test_as_insert_into_s3_query_with_parameters(self, ateam, data_interval_start, data_interval_end):
        model = SessionsRecordBatchModel(
            team_id=ateam.id,
        )
        printed_query, _ = await model.as_insert_into_s3_query_with_parameters(
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
