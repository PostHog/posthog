import re
from io import BytesIO

from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq

from products.data_warehouse.backend.webhook_consumer.writer import PARQUET_SCHEMA, WebhookParquetWriter


class TestWebhookParquetWriter:
    def _make_table(self, rows: int = 3) -> pa.Table:
        return pa.table(
            {
                "team_id": pa.array([1] * rows, type=pa.int64()),
                "schema_id": pa.array(["test-schema"] * rows, type=pa.utf8()),
                "payload_json": pa.array(['{"key": "value"}'] * rows, type=pa.utf8()),
            }
        )

    @patch("products.data_warehouse.backend.webhook_consumer.writer.ensure_bucket")
    @patch("products.data_warehouse.backend.webhook_consumer.writer.get_s3_client")
    def test_write_returns_s3_path_with_uuid(self, mock_get_s3, mock_ensure_bucket):
        mock_s3 = MagicMock()
        mock_get_s3.return_value = mock_s3
        mock_s3.open.return_value.__enter__ = MagicMock(return_value=BytesIO())
        mock_s3.open.return_value.__exit__ = MagicMock(return_value=False)

        writer = WebhookParquetWriter()
        with patch("products.data_warehouse.backend.webhook_consumer.writer.settings") as mock_settings:
            mock_settings.DATAWAREHOUSE_BUCKET = "test-bucket"
            result = writer.write(self._make_table(), team_id=42, schema_id="schema-abc")

        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        assert re.match(
            rf"s3://test-bucket/source_webhook_producer/42/schema-abc/{uuid_pattern}\.parquet",
            result,
        )

    @patch("products.data_warehouse.backend.webhook_consumer.writer.ensure_bucket")
    @patch("products.data_warehouse.backend.webhook_consumer.writer.get_s3_client")
    def test_write_creates_valid_parquet(self, mock_get_s3, mock_ensure_bucket):
        buffer = BytesIO()
        mock_s3 = MagicMock()
        mock_get_s3.return_value = mock_s3
        mock_s3.open.return_value.__enter__ = MagicMock(return_value=buffer)
        mock_s3.open.return_value.__exit__ = MagicMock(return_value=False)

        writer = WebhookParquetWriter()
        table = self._make_table(rows=2)

        with patch("products.data_warehouse.backend.webhook_consumer.writer.settings") as mock_settings:
            mock_settings.DATAWAREHOUSE_BUCKET = "test-bucket"
            writer.write(table, team_id=1, schema_id="s")

        buffer.seek(0)
        read_table = pq.read_table(buffer)
        assert read_table.num_rows == 2
        assert read_table.schema.field("team_id").type == pa.int64()
        assert read_table.schema.field("schema_id").type == pa.utf8()
        assert read_table.schema.field("payload_json").type == pa.utf8()

    @patch("products.data_warehouse.backend.webhook_consumer.writer.ensure_bucket")
    @patch("products.data_warehouse.backend.webhook_consumer.writer.get_s3_client")
    def test_write_opens_correct_s3_path(self, mock_get_s3, mock_ensure_bucket):
        mock_s3 = MagicMock()
        mock_get_s3.return_value = mock_s3
        mock_s3.open.return_value.__enter__ = MagicMock(return_value=BytesIO())
        mock_s3.open.return_value.__exit__ = MagicMock(return_value=False)

        writer = WebhookParquetWriter()

        with patch("products.data_warehouse.backend.webhook_consumer.writer.settings") as mock_settings:
            mock_settings.DATAWAREHOUSE_BUCKET = "my-bucket"
            writer.write(self._make_table(), team_id=99, schema_id="my-schema")

        call_args = mock_s3.open.call_args[0][0]
        assert call_args.startswith("my-bucket/source_webhook_producer/99/my-schema/")
        assert call_args.endswith(".parquet")

    @patch("products.data_warehouse.backend.webhook_consumer.writer.ensure_bucket")
    @patch("products.data_warehouse.backend.webhook_consumer.writer.get_s3_client")
    def test_write_uses_zstd_compression(self, mock_get_s3, mock_ensure_bucket):
        buffer = BytesIO()
        mock_s3 = MagicMock()
        mock_get_s3.return_value = mock_s3
        mock_s3.open.return_value.__enter__ = MagicMock(return_value=buffer)
        mock_s3.open.return_value.__exit__ = MagicMock(return_value=False)

        writer = WebhookParquetWriter(compression="zstd")

        with patch("products.data_warehouse.backend.webhook_consumer.writer.settings") as mock_settings:
            mock_settings.DATAWAREHOUSE_BUCKET = "test-bucket"
            writer.write(self._make_table(), team_id=1, schema_id="s")

        buffer.seek(0)
        pf = pq.ParquetFile(buffer)
        metadata = pf.metadata
        assert metadata.row_group(0).column(0).compression == "ZSTD"

    def test_parquet_schema_constant(self):
        assert len(PARQUET_SCHEMA) == 3
        assert PARQUET_SCHEMA.field("team_id").type == pa.int64()
        assert PARQUET_SCHEMA.field("schema_id").type == pa.utf8()
        assert PARQUET_SCHEMA.field("payload_json").type == pa.utf8()
