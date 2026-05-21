from typing import Any

from unittest.mock import Mock, patch

from posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor import _process_batch
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import PendingBatch


def _make_batch(**overrides: Any) -> PendingBatch:
    defaults: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "team_id": 1,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "job_id": "job-1",
        "run_uuid": "run-1",
        "batch_index": 0,
        "s3_path": "s3://bucket/path",
        "row_count": 100,
        "byte_size": 1024,
        "is_final_batch": False,
        "total_batches": None,
        "total_rows": None,
        "sync_type": "incremental",
        "cumulative_row_count": 0,
        "resource_name": "test_resource",
        "is_resume": False,
        "is_first_ever_sync": False,
        "metadata": {},
        "latest_attempt": 0,
    }
    defaults.update(overrides)
    return PendingBatch(**defaults)


def _make_schema() -> Mock:
    schema = Mock()
    schema.normalized_name = "customers"
    schema.source.source_type = "Stripe"
    schema.source.prefix = None
    return schema


def test_first_incremental_batch_replaces_table() -> None:
    conn = Mock()
    batch = _make_batch(batch_index=0, is_resume=False, sync_type="incremental")

    with (
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_columns",
            return_value=["id", "email"],
        ),
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._replace_table") as replace_table,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists") as table_exists,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch") as merge_batch,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch") as insert_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    replace_table.assert_called_once()
    table_exists.assert_not_called()
    merge_batch.assert_not_called()
    insert_batch.assert_not_called()


def test_first_ever_incremental_followup_batch_inserts_without_primary_keys() -> None:
    conn = Mock()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=True,
        metadata={},
    )

    with (
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_columns",
            return_value=["id", "email"],
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch") as insert_batch,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch") as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    insert_batch.assert_called_once()
    merge_batch.assert_not_called()


def test_existing_incremental_table_merges_after_first_sync() -> None:
    conn = Mock()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    with (
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_columns",
            return_value=["id", "email"],
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch") as insert_batch,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch") as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    insert_batch.assert_not_called()
    merge_batch.assert_called_once()


def test_missing_table_is_created_from_parquet() -> None:
    conn = Mock()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    with (
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_columns",
            return_value=["id", "email"],
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=False,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._create_table_from_parquet"
        ) as create_table,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch") as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    create_table.assert_called_once()
    merge_batch.assert_not_called()
