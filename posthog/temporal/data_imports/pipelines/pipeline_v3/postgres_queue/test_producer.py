import json
from typing import Any

from unittest.mock import MagicMock, PropertyMock, patch

from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import PostgresProducer
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult


def _make_producer(**kwargs: Any) -> PostgresProducer:
    defaults: dict[str, Any] = {
        "database_url": "postgres://unused:unused@localhost/unused",
        "team_id": 1,
        "job_id": "job-1",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "resource_name": "test_resource",
        "sync_type": "full_refresh",
        "run_uuid": "run-1",
        "logger": MagicMock(),
    }
    defaults.update(kwargs)
    with patch("posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.psycopg") as mock_psycopg:
        mock_conn = MagicMock()
        mock_psycopg.Connection.connect.return_value = mock_conn
        producer = PostgresProducer(**defaults)
    return producer


def _make_batch_result(batch_index: int = 0) -> BatchWriteResult:
    return BatchWriteResult(
        batch_index=batch_index,
        s3_path="s3://bucket/path",
        row_count=100,
        byte_size=1024,
        timestamp_ns=123456789,
    )


def _mock_conn(producer: PostgresProducer) -> Any:
    return producer._conn


class TestPostgresProducerSendBatch:
    def test_inserts_row_on_send(self) -> None:
        producer = _make_producer()
        batch_result = _make_batch_result()

        producer.send_batch_notification(batch_result)

        mock = _mock_conn(producer)
        mock.execute.assert_called_once()
        sql = mock.execute.call_args[0][0]
        params = mock.execute.call_args[0][1]
        assert "INSERT INTO" in sql
        assert params["team_id"] == 1
        assert params["s3_path"] == "s3://bucket/path"
        assert params["row_count"] == 100
        assert params["batch_index"] == 0

    def test_metadata_includes_optional_fields(self) -> None:
        producer = _make_producer(
            primary_keys=["id"],
            partition_count=4,
            cdc_write_mode="upsert",
            cdc_table_mode="merge",
        )
        batch_result = _make_batch_result()

        producer.send_batch_notification(batch_result)

        mock = _mock_conn(producer)
        params = mock.execute.call_args[0][1]
        metadata = json.loads(params["metadata"])
        assert metadata["primary_keys"] == ["id"]
        assert metadata["partition_count"] == 4
        assert metadata["cdc_write_mode"] == "upsert"
        assert metadata["cdc_table_mode"] == "merge"
        assert metadata["timestamp_ns"] == 123456789


class TestPostgresProducerFlush:
    def test_returns_count_and_resets(self) -> None:
        producer = _make_producer()
        producer.send_batch_notification(_make_batch_result(0))
        producer.send_batch_notification(_make_batch_result(1))
        producer.send_batch_notification(_make_batch_result(2))

        count = producer.flush()

        assert count == 3

        count = producer.flush()
        assert count == 0

    def test_flush_with_no_batches(self) -> None:
        producer = _make_producer()

        assert producer.flush() == 0


class TestPostgresProducerClose:
    def test_closes_connection(self) -> None:
        producer = _make_producer()
        mock = _mock_conn(producer)
        type(mock).closed = PropertyMock(return_value=False)

        producer.close()

        mock.close.assert_called_once()

    def test_close_idempotent(self) -> None:
        producer = _make_producer()
        mock = _mock_conn(producer)
        type(mock).closed = PropertyMock(return_value=True)

        producer.close()

        mock.close.assert_not_called()


class TestPostgresProducerProperties:
    def test_sync_type_property(self) -> None:
        producer = _make_producer(sync_type="incremental")

        assert producer.sync_type == "incremental"

    def test_is_first_ever_sync_property(self) -> None:
        producer = _make_producer(is_first_ever_sync=True)

        assert producer.is_first_ever_sync is True

        producer.is_first_ever_sync = False
        assert producer.is_first_ever_sync is False
