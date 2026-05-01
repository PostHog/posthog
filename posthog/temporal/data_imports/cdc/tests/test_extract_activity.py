import uuid
from datetime import UTC, datetime
from typing import Literal

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.cdc.activities import CDCExtractActivity, CDCExtractInput, cdc_extract_activity
from posthog.temporal.data_imports.cdc.types import ChangeEvent


def _make_event(
    op: Literal["I", "U", "D"] = "I",
    table: str = "users",
    position: str = "0/100",
    columns: dict | None = None,
) -> ChangeEvent:
    return ChangeEvent(
        operation=op,
        table_name=table,
        position_serialized=position,
        timestamp=datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC),
        columns=columns or {"id": 1, "name": "Alice"},
    )


def _make_source(source_id=None, job_inputs=None):
    source = MagicMock()
    source.id = source_id or uuid.uuid4()
    source.team_id = 1
    source.source_type = "Postgres"
    source.deleted = False
    source.job_inputs = (
        job_inputs
        if job_inputs is not None
        else {
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "user": "test",
            "password": "test",
            "cdc_slot_name": "posthog_slot",
            "cdc_publication_name": "posthog_pub",
        }
    )
    return source


def _make_schema(name, cdc_mode="streaming", cdc_table_mode="consolidated", source=None, schema_id=None):
    schema = MagicMock()
    schema.id = schema_id or uuid.uuid4()
    schema.name = name
    schema.team_id = 1
    schema.source = source
    schema.sync_type = "cdc"
    schema.sync_type_config = {"cdc_mode": cdc_mode, "cdc_table_mode": cdc_table_mode}
    schema.is_cdc = True
    schema.cdc_mode = cdc_mode
    schema.cdc_table_mode = cdc_table_mode
    schema.should_sync = True
    schema.deleted = False
    schema.save = MagicMock()
    return schema


# Shared patch decorator for CDC activity tests
_CDC_ACTIVITY_PATCHES = [
    "posthog.temporal.data_imports.cdc.activities.close_old_connections",
    "posthog.temporal.data_imports.cdc.activities.ExternalDataJob",
    "posthog.temporal.data_imports.cdc.activities.ExternalDataSource",
    "posthog.temporal.data_imports.cdc.activities.CDCExtractActivity._get_cdc_schemas",
    "posthog.temporal.data_imports.cdc.activities.get_cdc_adapter",
    "posthog.temporal.data_imports.cdc.activities.S3BatchWriter",
    "posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer",
    "posthog.temporal.data_imports.cdc.activities.activity",
]


def _setup_mocks(
    mock_activity,
    MockProducer,
    MockS3Writer,
    mock_get_adapter,
    mock_get_schemas,
    MockSourceModel,
    MockJob,
    mock_close_conns,
    source,
    schemas,
    events,
):
    """Wire up the standard mocks for CDC activity tests."""
    MockSourceModel.objects.get.return_value = source
    mock_get_schemas.return_value = schemas

    mock_reader = MagicMock()
    mock_reader.read_changes.return_value = iter(events)
    mock_reader.truncated_tables = []
    mock_reader.get_decoder_key_columns.return_value = []
    mock_adapter = MagicMock()
    mock_adapter.create_reader.return_value = mock_reader
    mock_get_adapter.return_value = mock_adapter

    mock_s3 = MagicMock()
    mock_batch_result = MagicMock()
    mock_batch_result.s3_path = "s3://bucket/data/part-0000.parquet"
    mock_batch_result.row_count = len(events)
    mock_batch_result.byte_size = 512
    mock_batch_result.batch_index = 0
    mock_batch_result.timestamp_ns = 123456
    mock_s3.write_batch.return_value = mock_batch_result
    mock_s3.write_schema.return_value = "s3://bucket/schema.json"
    mock_s3.get_data_folder.return_value = "s3://bucket/data/"
    MockS3Writer.return_value = mock_s3

    mock_producer = MagicMock()
    MockProducer.return_value = mock_producer

    mock_job = MagicMock()
    mock_job.id = uuid.uuid4()
    MockJob.objects.create.return_value = mock_job
    MockJob.PipelineVersion.V2 = "v2-non-dlt"
    MockJob.Status.RUNNING = "Running"
    MockJob.Status.COMPLETED = "Completed"
    MockJob.Status.FAILED = "Failed"

    mock_activity.heartbeat = MagicMock()
    mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1")

    return mock_reader, mock_s3, mock_producer, mock_job


class TestGetCDCAdapter:
    def test_returns_postgres_adapter(self):
        from posthog.temporal.data_imports.cdc.adapters import get_cdc_adapter
        from posthog.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter

        source = _make_source()
        adapter = get_cdc_adapter(source)
        assert isinstance(adapter, PostgresCDCAdapter)

    def test_raises_for_unsupported_source(self):
        from posthog.temporal.data_imports.cdc.adapters import get_cdc_adapter

        source = _make_source()
        source.source_type = "UnsupportedDB"
        with pytest.raises(ValueError, match="CDC is not supported"):
            get_cdc_adapter(source)

    def test_create_reader_extracts_params(self):
        from posthog.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter
        from posthog.temporal.data_imports.sources.postgres.cdc.stream_reader import PgCDCStreamReader

        adapter = PostgresCDCAdapter()
        source = _make_source()
        reader = adapter.create_reader(source)
        assert isinstance(reader, PgCDCStreamReader)

        assert reader._params.host == "localhost"
        assert reader._params.port == 5432
        assert reader._params.database == "testdb"
        assert reader._params.slot_name == "posthog_slot"
        assert reader._params.publication_name == "posthog_pub"

    def test_create_reader_defaults_when_missing(self):
        from posthog.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter
        from posthog.temporal.data_imports.sources.postgres.cdc.stream_reader import PgCDCStreamReader

        adapter = PostgresCDCAdapter()
        source = _make_source(job_inputs={})
        reader = adapter.create_reader(source)
        assert isinstance(reader, PgCDCStreamReader)

        assert reader._params.host == ""
        assert reader._params.port == 5432
        assert reader._params.sslmode == "prefer"
        assert reader._params.slot_name == ""


def _make_extract_activity(source, log=None) -> CDCExtractActivity:
    """Build a CDCExtractActivity with source and log pre-injected for unit tests."""
    activity_obj = CDCExtractActivity(CDCExtractInput(team_id=1, source_id=source.id))
    activity_obj.source = source
    activity_obj.log = log or MagicMock()
    return activity_obj


class TestFlushDeferredRuns:
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    def test_sends_kafka_messages_for_deferred_runs(self, MockProducer):
        mock_producer = MagicMock()
        MockProducer.return_value = mock_producer

        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_deferred_runs"] = [
            {
                "job_id": "job-1",
                "run_uuid": "run-1",
                "data_folder": "s3://bucket/data/",
                "schema_path": "s3://bucket/schema.json",
                "total_batches": 1,
                "total_rows": 10,
                "batch_results": [
                    {
                        "s3_path": "s3://bucket/data/part-0000.parquet",
                        "row_count": 10,
                        "byte_size": 1024,
                        "batch_index": 0,
                        "timestamp_ns": 123456789,
                    }
                ],
            }
        ]

        _make_extract_activity(source)._flush_deferred_runs(schema)

        mock_producer.send_batch_notification.assert_called_once()
        mock_producer.flush.assert_called_once()

        assert schema.sync_type_config["cdc_deferred_runs"] == []
        schema.save.assert_called()

    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    def test_no_op_when_no_deferred_runs(self, MockProducer):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config = {"cdc_mode": "streaming"}

        _make_extract_activity(source)._flush_deferred_runs(schema)

        MockProducer.assert_not_called()
        schema.save.assert_not_called()

    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    def test_multiple_deferred_runs(self, MockProducer):
        mock_producer = MagicMock()
        MockProducer.return_value = mock_producer

        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_deferred_runs"] = [
            {
                "job_id": f"job-{i}",
                "run_uuid": f"run-{i}",
                "data_folder": f"s3://bucket/data-{i}/",
                "schema_path": f"s3://bucket/schema-{i}.json",
                "total_batches": 1,
                "total_rows": 5,
                "batch_results": [
                    {
                        "s3_path": f"s3://bucket/data-{i}/part-0000.parquet",
                        "row_count": 5,
                        "byte_size": 512,
                        "batch_index": 0,
                    }
                ],
            }
            for i in range(3)
        ]

        _make_extract_activity(source)._flush_deferred_runs(schema)

        # 3 deferred runs, each with 1 batch → 3 send calls, 3 flush calls (one per producer)
        assert mock_producer.send_batch_notification.call_count == 3
        assert mock_producer.flush.call_count == 3
        assert schema.sync_type_config["cdc_deferred_runs"] == []


class TestCDCExtractActivity:
    """Integration tests for cdc_extract_activity with mocked external deps."""

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_streaming_schema_writes_s3_and_sends_kafka(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"}),
            _make_event(op="U", table="users", position="0/200", columns={"id": 1, "name": "Bob"}),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        mock_reader.connect.assert_called_once()
        mock_s3.write_batch.assert_called_once()
        mock_producer.send_batch_notification.assert_called_once()
        mock_producer.flush.assert_called_once()
        mock_reader.confirm_position.assert_called_once_with("0/200")
        mock_reader.close.assert_called_once()

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_streaming_job_not_marked_completed_by_activity(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        """For streaming schemas, the activity should NOT mark the job as COMPLETED.
        The Kafka consumer marks it after loading to DeltaLake."""
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # No save call for the job should include "status" in update_fields
        mock_job.save.assert_called()
        for call in mock_job.save.call_args_list:
            assert "status" not in call.kwargs.get("update_fields", [])

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_snapshot_schema_writes_s3_defers_kafka_and_marks_job_completed(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        """Snapshot schemas write to S3 and defer the Kafka notification (stored in
        sync_type_config) until the schema transitions to streaming. The job is marked
        COMPLETED immediately since no Kafka consumer will process it."""
        source = _make_source()
        schema = _make_schema("users", cdc_mode="snapshot", source=source)
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        mock_s3.write_batch.assert_called_once()
        MockProducer.assert_not_called()

        deferred = schema.sync_type_config.get("cdc_deferred_runs", [])
        assert len(deferred) == 1
        assert deferred[0]["run_uuid"] is not None
        assert deferred[0]["total_rows"] == 1

        mock_reader.confirm_position.assert_called_once_with("0/100")

        # Job is completed by the activity (no Kafka consumer to do it)
        assert any("status" in call.kwargs.get("update_fields", []) for call in mock_job.save.call_args_list)

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_no_changes_returns_early_with_completed_status(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source

        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.return_value = iter([])
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_get_adapter.return_value = mock_adapter

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # No slot advance and reader still cleaned up
        mock_reader.confirm_position.assert_not_called()
        mock_reader.close.assert_called_once()

        # Schema marked completed even with no changes
        schema.save.assert_called()
        assert schema.status == "Completed"
        assert schema.latest_error is None
        assert schema.last_synced_at is not None

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_no_cdc_schemas_returns_early(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        mock_get_schemas.return_value = []

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        mock_get_adapter.assert_not_called()

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_events_for_unknown_tables_are_filtered(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="users", position="0/100"),
            _make_event(op="I", table="other_table", position="0/200"),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Only 1 S3 write (for "users"), not for "other_table"
        mock_s3.write_batch.assert_called_once()
        call_args = mock_s3.write_batch.call_args
        pa_table = call_args[0][0]
        assert pa_table.num_rows == 1

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_reader_closed_on_error(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source

        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.side_effect = RuntimeError("connection lost")
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_get_adapter.return_value = mock_adapter

        inputs = CDCExtractInput(team_id=1, source_id=source.id)

        with pytest.raises(RuntimeError, match="connection lost"):
            cdc_extract_activity(inputs)

        mock_reader.close.assert_called_once()

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_schema_status_set_to_failed_on_error(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        # Make S3 write fail
        mock_s3.write_batch.side_effect = RuntimeError("S3 write failed")

        inputs = CDCExtractInput(team_id=1, source_id=source.id)

        with pytest.raises(RuntimeError, match="S3 write failed"):
            cdc_extract_activity(inputs)

        # Schema should be marked as FAILED
        assert schema.status == "Failed"
        assert "S3 write failed" in schema.latest_error

        # Slot should NOT have been advanced
        mock_reader.confirm_position.assert_not_called()

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_cdc_last_log_position_updated_per_schema(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="users", position="0/100"),
            _make_event(op="U", table="users", position="0/200"),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # cdc_last_log_position should be updated to the last event's position
        assert schema.sync_type_config["cdc_last_log_position"] == "0/200"

    @patch("posthog.temporal.data_imports.cdc.activities.unpause_external_data_schedule", create=True)
    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_truncate_only_batch_sets_snapshot_and_advances_slot(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
        mock_unpause,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source

        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.return_value = iter([])  # no DML events
        mock_reader.truncated_tables = ["users"]
        mock_reader.last_commit_end_lsn = "0/500"
        mock_reader.get_decoder_key_columns.return_value = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1")

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.initial_sync_complete is False
        mock_reader.confirm_position.assert_called_once_with("0/500")

    @patch("posthog.temporal.data_imports.cdc.activities.unpause_external_data_schedule", create=True)
    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_truncate_sets_snapshot_mode(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
        mock_unpause,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        # Simulate a truncate for the "users" table
        mock_reader.truncated_tables = ["users"]

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Schema should be set back to snapshot mode
        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.initial_sync_complete is False
        assert "cdc_last_log_position" not in schema.sync_type_config

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_multi_table_events_grouped_correctly(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        users_schema = _make_schema("users", cdc_mode="streaming", source=source)
        orders_schema = _make_schema("orders", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"}),
            _make_event(op="I", table="orders", position="0/200", columns={"id": 10, "total": 99}),
            _make_event(op="U", table="users", position="0/300", columns={"id": 1, "name": "Bob"}),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [users_schema, orders_schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Should have 2 S3 writes (one for users, one for orders)
        assert mock_s3.write_batch.call_count == 2

        # Should have 2 Kafka producers (one for each table)
        assert MockProducer.call_count == 2

        # Slot should advance to the last event's position
        mock_reader.confirm_position.assert_called_once_with("0/300")

    @patch("posthog.temporal.data_imports.cdc.activities.unpause_external_data_schedule", create=True)
    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_truncated_schema_log_position_not_updated(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
        mock_unpause,
    ):
        """A schema reset to snapshot mode by a TRUNCATE should not have
        cdc_last_log_position updated — it will re-snapshot from scratch."""
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_last_log_position"] = "0/OLD"
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )
        mock_reader.truncated_tables = ["users"]

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        assert schema.sync_type_config.get("cdc_mode") == "snapshot"
        assert schema.sync_type_config.get("cdc_last_log_position") is None

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_both_mode_creates_two_trackers(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_table_mode"] = "both"
        schema.cdc_table_mode = "both"
        events = [_make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"})]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Two S3 writes: one for the consolidated table, one for the _cdc table
        assert mock_s3.write_batch.call_count == 2

        written_tables = [call[0][0] for call in mock_s3.write_batch.call_args_list]
        consolidated_table = written_tables[0]
        cdc_table = written_tables[1]

        # Consolidated table: 1 row (deduplicated INSERT), no valid_from/valid_to
        assert consolidated_table.num_rows == 1
        assert "valid_from" not in consolidated_table.column_names
        assert "valid_to" not in consolidated_table.column_names

        # _cdc table: 1 row with SCD2 columns
        assert cdc_table.num_rows == 1
        assert "valid_from" in cdc_table.column_names
        assert "valid_to" in cdc_table.column_names

        # Two Kafka producers: one with incremental_merge, one with scd2_append
        assert MockProducer.call_count == 2
        write_modes = {call.kwargs["cdc_write_mode"] for call in MockProducer.call_args_list}
        assert write_modes == {"incremental_merge", "scd2_append"}

        resource_names = {call.kwargs["resource_name"] for call in MockProducer.call_args_list}
        assert resource_names == {"users", "users_cdc"}

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_cdc_only_mode_creates_single_cdc_tracker(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_table_mode"] = "cdc_only"
        schema.cdc_table_mode = "cdc_only"
        events = [_make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"})]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Only one S3 write for the _cdc resource
        mock_s3.write_batch.assert_called_once()
        written_table = mock_s3.write_batch.call_args[0][0]
        assert written_table.num_rows == 1
        assert "valid_from" in written_table.column_names
        assert "valid_to" in written_table.column_names

        # Only one Kafka producer with scd2_append and _cdc resource name
        assert MockProducer.call_count == 1
        producer_kwargs = MockProducer.call_args.kwargs
        assert producer_kwargs["resource_name"] == "users_cdc"
        assert producer_kwargs["cdc_write_mode"] == "scd2_append"

    @patch("posthog.temporal.data_imports.cdc.activities.ChangeEventBatcher")
    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_micro_batch_flush_sends_kafka_immediately(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
        MockBatcher,
    ):
        from posthog.temporal.data_imports.cdc.batcher import ChangeEventBatcher as RealBatcher

        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_table_mode"] = "consolidated"
        schema.cdc_table_mode = "consolidated"
        events = [
            _make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"}),
            _make_event(op="I", table="users", position="0/200", columns={"id": 2, "name": "Bob"}),
            _make_event(op="I", table="users", position="0/300", columns={"id": 3, "name": "Charlie"}),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        # Use a real batcher with max_events=2 so after the 2nd event should_flush is True
        MockBatcher.return_value = RealBatcher(max_events=2)

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # 2 events trigger a micro-batch flush (non-final), then 1 event triggers the final flush
        # Each flush produces one S3 write and one Kafka send
        assert mock_s3.write_batch.call_count == 2
        assert mock_producer.send_batch_notification.call_count == 2

        # Micro-batch (first call) is NOT the final batch; final flush IS
        send_calls = mock_producer.send_batch_notification.call_args_list
        assert send_calls[0].kwargs["is_final_batch"] is False
        assert send_calls[1].kwargs["is_final_batch"] is True

    @patch("posthog.temporal.data_imports.cdc.activities.activity")
    @patch("posthog.temporal.data_imports.cdc.activities.KafkaBatchProducer")
    @patch("posthog.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("posthog.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("posthog.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("posthog.temporal.data_imports.cdc.activities.close_old_connections")
    def test_deferred_run_stored_per_batch_for_snapshot_schema(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="snapshot", source=source)
        schema.sync_type_config["cdc_table_mode"] = "consolidated"
        schema.cdc_table_mode = "consolidated"
        events = [
            _make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"}),
            _make_event(op="I", table="users", position="0/200", columns={"id": 2, "name": "Bob"}),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Snapshot mode defers Kafka — no producer should be created during extraction
        MockProducer.assert_not_called()

        # Exactly one deferred run entry (one tracker for the consolidated table)
        deferred = schema.sync_type_config.get("cdc_deferred_runs", [])
        assert len(deferred) == 1

        entry = deferred[0]
        assert entry["run_uuid"] is not None
        assert len(entry["batch_results"]) == 1
        batch = entry["batch_results"][0]
        assert batch["s3_path"] == "s3://bucket/data/part-0000.parquet"
        assert batch["row_count"] == len(events)

        # Job should be marked COMPLETED by the activity (no Kafka consumer will do it)
        assert any("status" in call.kwargs.get("update_fields", []) for call in mock_job.save.call_args_list)
