from __future__ import annotations

import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from posthog.sync import database_sync_to_async
from posthog.temporal.ducklake.promote_table_workflow import (
    CleanupPreviousRunInputs,
    MarkFailureInputs,
    PromoteTableCopyResult,
    PromoteTableInputs,
    PromoteTableMetadata,
    _build_destination_uri,
    _build_url_pattern,
    _execute_copy_to_parquet,
    _previous_run_uri,
    cleanup_previous_run_activity,
    mark_promotion_failed_activity,
)


class TestUrlHelpers:
    @pytest.mark.parametrize(
        "team_id,promoted_id,run_id,expected",
        [
            (
                42,
                "abc-123",
                "run-xyz",
                "s3://my-bucket/__posthog_promoted/team_42/abc-123/run_run-xyz/",
            ),
            (
                1,
                "promoted",
                "RUN",
                "s3://my-bucket/__posthog_promoted/team_1/promoted/run_RUN/",
            ),
        ],
    )
    def test_build_destination_uri(self, team_id, promoted_id, run_id, expected):
        assert _build_destination_uri("my-bucket", team_id, promoted_id, run_id) == expected

    def test_build_url_pattern_strips_trailing_slash_and_appends_glob(self):
        assert (
            _build_url_pattern("s3://b/__posthog_promoted/team_1/p/run_x/")
            == "s3://b/__posthog_promoted/team_1/p/run_x/*.parquet"
        )

    @pytest.mark.parametrize(
        "url_pattern,expected",
        [
            ("s3://b/path/run_1/*.parquet", "s3://b/path/run_1/"),
            ("s3://b/path/run_1/*", "s3://b/path/run_1/"),
            ("", None),
            ("s3://b/path/run_1/file.parquet", None),
        ],
    )
    def test_previous_run_uri(self, url_pattern, expected):
        assert _previous_run_uri(url_pattern) == expected


class TestExecuteCopyToParquet:
    def test_emits_count_then_copy_with_quoted_identifiers_and_destination(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (123,)

        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        conn.cursor.return_value.__exit__.return_value = None

        row_count = _execute_copy_to_parquet(
            conn,
            schema_name="my_schema",
            table_name="my_table",
            destination_uri="s3://bucket/path/run_1/",
        )

        assert row_count == 123
        assert cursor.execute.call_count == 2

        count_sql = cursor.execute.call_args_list[0][0][0]
        copy_sql = cursor.execute.call_args_list[1][0][0]

        rendered_count = count_sql.as_string(None)
        rendered_copy = copy_sql.as_string(None)

        assert '"my_schema"."my_table"' in rendered_count
        assert '"my_schema"."my_table"' in rendered_copy
        assert "FORMAT PARQUET" in rendered_copy
        assert "PER_THREAD_OUTPUT TRUE" in rendered_copy
        assert "'s3://bucket/path/run_1/'" in rendered_copy

    def test_escapes_identifiers_containing_special_chars(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (0,)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        conn.cursor.return_value.__exit__.return_value = None

        _execute_copy_to_parquet(
            conn,
            schema_name='evil"schema',
            table_name="t",
            destination_uri="s3://b/p/",
        )

        rendered_copy = cursor.execute.call_args_list[1][0][0].as_string(None)
        # Embedded double quotes must be doubled per SQL identifier escaping rules.
        assert '"evil""schema"."t"' in rendered_copy

    def test_escapes_destination_uri_quotes(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (0,)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        conn.cursor.return_value.__exit__.return_value = None

        _execute_copy_to_parquet(
            conn,
            schema_name="s",
            table_name="t",
            destination_uri="s3://b/'evil'/",
        )

        rendered_copy = cursor.execute.call_args_list[1][0][0].as_string(None)
        # psql.Literal must escape single quotes inside the URI.
        assert "'s3://b/''evil''/'" in rendered_copy

    def test_zero_count_when_table_empty(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (None,)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        conn.cursor.return_value.__exit__.return_value = None

        assert _execute_copy_to_parquet(conn, "s", "t", "s3://b/p/") == 0


@pytest.mark.asyncio
async def test_input_dataclasses_round_trip_via_temporal_codec():
    import temporalio.converter

    inputs = PromoteTableInputs(team_id=7, promoted_table_id="prom-1")
    metadata = PromoteTableMetadata(
        team_id=7,
        promoted_table_id="prom-1",
        source_schema_name="public",
        source_table_name="users",
        catalog_bucket="b",
        catalog_region="us-east-1",
        catalog_role_arn="arn:aws:iam::1:role/r",
        catalog_external_id="x",
        destination_uri="s3://b/p/run_1/",
        destination_url_pattern="s3://b/p/run_1/*.parquet",
        previous_url_pattern=None,
    )
    copy = PromoteTableCopyResult(row_count=10, size_in_s3_mib=None)
    cleanup = CleanupPreviousRunInputs(
        team_id=7, catalog_role_arn="arn:aws:iam::1:role/r", catalog_external_id="x", previous_run_uri="s3://b/p/run_0/"
    )
    fail = MarkFailureInputs(team_id=7, promoted_table_id="prom-1", error_message="boom")

    converter = temporalio.converter.default()
    for original, types in [
        (inputs, [PromoteTableInputs]),
        (metadata, [PromoteTableMetadata]),
        (copy, [PromoteTableCopyResult]),
        (cleanup, [CleanupPreviousRunInputs]),
        (fail, [MarkFailureInputs]),
    ]:
        encoded = await converter.encode([original])
        decoded = await converter.decode(encoded, types)
        assert decoded[0] == original


@pytest.mark.asyncio
async def test_cleanup_previous_run_activity_swallows_errors():
    inputs = CleanupPreviousRunInputs(
        team_id=1,
        catalog_role_arn="arn",
        catalog_external_id="x",
        previous_run_uri="s3://b/p/run_0/",
    )
    with patch(
        "posthog.temporal.ducklake.promote_table_workflow.cleanup_staged_files",
        side_effect=RuntimeError("nope"),
    ):
        # Should not raise.
        cleanup_previous_run_activity(inputs)


@pytest.mark.asyncio
async def test_cleanup_previous_run_activity_calls_cleanup_helper():
    inputs = CleanupPreviousRunInputs(
        team_id=1,
        catalog_role_arn="arn",
        catalog_external_id="x",
        previous_run_uri="s3://b/p/run_0/",
    )
    with patch("posthog.temporal.ducklake.promote_table_workflow.cleanup_staged_files") as mock_cleanup:
        cleanup_previous_run_activity(inputs)
    mock_cleanup.assert_called_once_with(staging_uri="s3://b/p/run_0/", role_arn="arn", external_id="x")


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_mark_promotion_failed_activity_truncates_long_errors(ateam):
    from products.data_warehouse.backend.models import ManagedWarehousePromotedTable

    promoted = await database_sync_to_async(ManagedWarehousePromotedTable.objects.create)(
        team=ateam,
        source_schema_name="s",
        source_table_name="t",
        sync_frequency_interval=dt.timedelta(hours=1),
    )

    long_error = "x" * 10000
    await mark_promotion_failed_activity(
        MarkFailureInputs(team_id=ateam.id, promoted_table_id=str(promoted.id), error_message=long_error)
    )

    refreshed = await database_sync_to_async(ManagedWarehousePromotedTable.objects.get)(id=promoted.id)
    assert refreshed.status == ManagedWarehousePromotedTable.Status.FAILED
    assert refreshed.last_error is not None
    assert len(refreshed.last_error) == 5000
