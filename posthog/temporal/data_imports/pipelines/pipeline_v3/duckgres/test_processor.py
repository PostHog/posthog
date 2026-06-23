from typing import Any

from unittest.mock import MagicMock, Mock, patch

from posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor import (
    DuckgresColumn,
    _ensure_duckgres_apply_table,
    _insert_batch,
    _mark_duckgres_batch_applied,
    _process_batch,
)
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


def _make_conn() -> MagicMock:
    return MagicMock()


def _parquet_schema() -> list[DuckgresColumn]:
    return [DuckgresColumn("id", "BIGINT"), DuckgresColumn("email", "VARCHAR")]


class _RecordingTransaction:
    def __init__(self, conn: "_RecordingConn") -> None:
        self.conn = conn

    def __enter__(self) -> None:
        self.conn.in_transaction = True
        self.conn.events.append("transaction:start")

    def __exit__(self, *args: object) -> None:
        self.conn.events.append("transaction:end")
        self.conn.in_transaction = False


class _RecordingConn:
    def __init__(self) -> None:
        self.execute = MagicMock()
        self.events: list[str] = []
        self.in_transaction = False

    def transaction(self) -> _RecordingTransaction:
        return _RecordingTransaction(self)


def test_first_ever_incremental_batch_replaces_table() -> None:
    conn = _make_conn()
    batch = _make_batch(batch_index=0, is_first_ever_sync=True, is_resume=False, sync_type="incremental")

    with (
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
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


def test_existing_incremental_batch_zero_merges_after_first_sync() -> None:
    conn = _make_conn()
    batch = _make_batch(
        batch_index=0,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    with (
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._replace_table") as replace_table,
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_target_columns",
            create=True,
        ) as ensure_columns,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch") as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    replace_table.assert_not_called()
    ensure_columns.assert_called_once_with(conn, "posthog_data_imports_team_1", "stripe_customers", _parquet_schema())
    merge_batch.assert_called_once()


def test_first_ever_incremental_followup_batch_inserts_without_primary_keys() -> None:
    conn = _make_conn()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=True,
        metadata={},
    )

    with (
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_target_columns",
            create=True,
        ) as ensure_columns,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch") as insert_batch,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch") as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    ensure_columns.assert_called_once_with(conn, "posthog_data_imports_team_1", "stripe_customers", _parquet_schema())
    insert_batch.assert_called_once()
    merge_batch.assert_not_called()


def test_existing_incremental_table_merges_after_first_sync() -> None:
    conn = _make_conn()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    with (
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_target_columns",
            create=True,
        ) as ensure_columns,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch") as insert_batch,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch") as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    ensure_columns.assert_called_once_with(conn, "posthog_data_imports_team_1", "stripe_customers", _parquet_schema())
    insert_batch.assert_not_called()
    merge_batch.assert_called_once()


def test_schema_evolution_merge_and_apply_marker_are_one_transaction() -> None:
    conn: Any = _RecordingConn()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    def ensure_columns(*args: object) -> None:
        assert conn.in_transaction
        conn.events.append("ensure_columns")

    def merge_batch(*args: object) -> None:
        assert conn.in_transaction
        conn.events.append("merge")

    def mark_applied(*args: object, **kwargs: object) -> None:
        assert conn.in_transaction
        conn.events.append("mark")

    with (
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._table_exists",
            return_value=True,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_target_columns",
            side_effect=ensure_columns,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch",
            side_effect=merge_batch,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._mark_duckgres_batch_applied",
            side_effect=mark_applied,
        ),
    ):
        _process_batch(conn, batch, _make_schema())

    assert conn.events == ["transaction:start", "ensure_columns", "merge", "mark", "transaction:end"]


def test_missing_table_is_created_from_parquet() -> None:
    conn = _make_conn()
    batch = _make_batch(
        batch_index=1,
        sync_type="incremental",
        is_first_ever_sync=False,
        metadata={"primary_keys": ["id"]},
    )

    with (
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table"),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            return_value=False,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
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


def test_insert_batch_uses_explicit_column_projection() -> None:
    conn = _make_conn()

    _insert_batch(conn, "warehouse", "customers", "s3://bucket/path", ["id", "email"])

    query = conn.execute.call_args.args[0]
    assert "SELECT *" not in repr(query)
    assert conn.execute.call_args.args[1] == ["s3://bucket/path"]


def test_already_applied_batch_skips_duckgres_mutation() -> None:
    conn = _make_conn()
    batch = _make_batch(batch_index=0, is_first_ever_sync=True)

    with (
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table",
            create=True,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            create=True,
            return_value=True,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ) as read_schema,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._replace_table") as replace_table,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._insert_batch") as insert_batch,
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._merge_batch") as merge_batch,
    ):
        _process_batch(conn, batch, _make_schema())

    read_schema.assert_not_called()
    replace_table.assert_not_called()
    insert_batch.assert_not_called()
    merge_batch.assert_not_called()


def test_marks_duckgres_batch_applied_after_successful_mutation() -> None:
    conn = _make_conn()
    batch = _make_batch(batch_index=0, is_first_ever_sync=True)

    with (
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._ensure_duckgres_apply_table",
            create=True,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._has_duckgres_batch_applied",
            create=True,
            return_value=False,
        ),
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._read_parquet_schema",
            return_value=_parquet_schema(),
        ),
        patch("posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._replace_table") as replace_table,
        patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.processor._mark_duckgres_batch_applied",
            create=True,
        ) as mark_applied,
    ):
        _process_batch(conn, batch, _make_schema())

    replace_table.assert_called_once()
    mark_applied.assert_called_once_with(conn, "posthog_data_imports_team_1", batch=batch)


def test_duckgres_apply_marker_is_scoped_by_schema_id() -> None:
    conn = _make_conn()
    batch = _make_batch(schema_id="schema-1", run_uuid="run-1", batch_index=2)

    _ensure_duckgres_apply_table(conn, "warehouse")
    create_query = conn.execute.call_args.args[0]

    assert "schema_id" in repr(create_query)
    assert "PRIMARY KEY (schema_id, run_uuid, batch_index)" in repr(create_query)

    _mark_duckgres_batch_applied(conn, "warehouse", batch=batch)

    query = conn.execute.call_args.args[0]
    assert "ON CONFLICT (schema_id, run_uuid, batch_index)" in repr(query)
    assert conn.execute.call_args.args[1] == [
        "schema-1",
        "run-1",
        2,
        "00000000-0000-0000-0000-000000000001",
    ]
