import datetime as dt
from uuid import uuid4

from freezegun import freeze_time
from unittest import TestCase, mock

from parameterized import parameterized

from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.temporal.data_imports.metrics import DATA_IMPORT_APP_SOURCE, emit_data_import_app_metrics

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob


def _make_job(
    *,
    status: str,
    rows_synced: int | None = 1234,
    finished_at: dt.datetime | None = None,
    team_id: int = 42,
) -> mock.Mock:
    job = mock.Mock(spec_set=("id", "team_id", "status", "rows_synced", "finished_at", "pipeline_id", "schema_id"))
    job.id = uuid4()
    job.team_id = team_id
    job.status = status
    job.rows_synced = rows_synced
    job.finished_at = finished_at or dt.datetime(2026, 4, 15, 12, 30, 45, tzinfo=dt.UTC)
    job.pipeline_id = uuid4()
    job.schema_id = uuid4()
    return job


class TestEmitDataImportAppMetrics(TestCase):
    @parameterized.expand(
        [
            (ExternalDataJob.Status.COMPLETED, "success", "succeeded"),
            (ExternalDataJob.Status.FAILED, "failure", "failed"),
            (ExternalDataJob.Status.BILLING_LIMIT_REACHED, "failure", "billing_limited"),
            (ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW, "failure", "billing_limited"),
        ]
    )
    def test_terminal_status_emits_expected_metric(self, status, expected_kind, expected_name):
        job = _make_job(status=status, rows_synced=1234)

        with mock.patch("posthog.temporal.data_imports.metrics.KafkaProducer") as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        produce_calls = mock_producer.produce.call_args_list
        assert len(produce_calls) == 2

        status_payload = produce_calls[0].kwargs["data"]
        assert produce_calls[0].kwargs["topic"] == KAFKA_APP_METRICS2
        assert status_payload["team_id"] == job.team_id
        assert status_payload["app_source"] == DATA_IMPORT_APP_SOURCE
        assert status_payload["app_source_id"] == str(job.pipeline_id)
        assert status_payload["instance_id"] == str(job.schema_id)
        assert status_payload["metric_kind"] == expected_kind
        assert status_payload["metric_name"] == expected_name
        assert status_payload["count"] == 1
        assert status_payload["timestamp"] == format_clickhouse_timestamp(job.finished_at)

        rows_payload = produce_calls[1].kwargs["data"]
        assert rows_payload["metric_kind"] == "rows"
        assert rows_payload["metric_name"] == "rows_synced"
        assert rows_payload["count"] == 1234
        assert rows_payload["timestamp"] == status_payload["timestamp"]

    def test_billing_statuses_collapse_to_same_metric_name(self):
        with mock.patch("posthog.temporal.data_imports.metrics.KafkaProducer") as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(_make_job(status=ExternalDataJob.Status.BILLING_LIMIT_REACHED))
            emit_data_import_app_metrics(_make_job(status=ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW))

        status_calls = [
            call for call in mock_producer.produce.call_args_list if call.kwargs["data"]["metric_kind"] == "failure"
        ]
        assert len(status_calls) == 2
        assert all(call.kwargs["data"]["metric_name"] == "billing_limited" for call in status_calls)

    @parameterized.expand(
        [
            ("zero", 0),
            ("null", None),
        ]
    )
    def test_rows_synced_suppressed_when_not_positive(self, _name, rows_synced):
        job = _make_job(status=ExternalDataJob.Status.COMPLETED, rows_synced=rows_synced)

        with mock.patch("posthog.temporal.data_imports.metrics.KafkaProducer") as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        produce_calls = mock_producer.produce.call_args_list
        assert len(produce_calls) == 1
        assert produce_calls[0].kwargs["data"]["metric_kind"] == "success"

    def test_non_terminal_status_emits_nothing(self):
        job = _make_job(status=ExternalDataJob.Status.RUNNING)

        with mock.patch("posthog.temporal.data_imports.metrics.KafkaProducer") as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        mock_producer_cls.assert_not_called()
        mock_producer.produce.assert_not_called()

    def test_kafka_producer_error_is_swallowed(self):
        job = _make_job(status=ExternalDataJob.Status.COMPLETED)

        with mock.patch("posthog.temporal.data_imports.metrics.KafkaProducer") as mock_producer_cls:
            mock_producer_cls.return_value.produce.side_effect = RuntimeError("kafka down")
            emit_data_import_app_metrics(job)

    def test_falls_back_to_now_when_finished_at_is_none(self):
        job = _make_job(status=ExternalDataJob.Status.COMPLETED)
        job.finished_at = None
        frozen_now = dt.datetime(2026, 4, 15, 9, 0, 0, tzinfo=dt.UTC)

        with (
            freeze_time(frozen_now),
            mock.patch("posthog.temporal.data_imports.metrics.KafkaProducer") as mock_producer_cls,
        ):
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        payload = mock_producer.produce.call_args_list[0].kwargs["data"]
        assert payload["timestamp"] == format_clickhouse_timestamp(frozen_now)

    def test_null_schema_id_becomes_empty_instance_id(self):
        job = _make_job(status=ExternalDataJob.Status.COMPLETED)
        job.schema_id = None

        with mock.patch("posthog.temporal.data_imports.metrics.KafkaProducer") as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        payload = mock_producer.produce.call_args_list[0].kwargs["data"]
        assert payload["instance_id"] == ""
