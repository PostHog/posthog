import json
from io import BytesIO

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
from kafka.errors import KafkaError

from posthog.models.hog_functions.hog_function import HogFunction
from posthog.temporal.data_imports.pipelines.pipeline.cdp_producer import CDPProducer

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.data_warehouse.backend.types import ExternalDataSourceType


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_no_hog_function(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is False


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_with_matching_hog_function(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is True


@pytest.mark.django_db(transaction=True)
def test_should_not_produce_table_with_disabled_matching_hog_function(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=False,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is False


@pytest.mark.django_db(transaction=True)
def test_should_not_produce_table_with_deleted_matching_hog_function(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=True,
        deleted=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is False


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_with_new_style_table_name(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres.table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is True


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_with_source_prefix(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES, prefix="eu")
    table = DataWarehouseTable.objects.create(team=team, name="postgres_eu_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.eu.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is True


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_with_leading_underscore_source_prefix(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES, prefix="_eu")
    table = DataWarehouseTable.objects.create(team=team, name="postgres_eu_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.eu.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is True


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.FakeKafka")
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.get_s3_client")
def test_produce_to_kafka_from_s3_success(mock_get_s3_client, mock_kafka_producer_class, team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_s3_client = MagicMock()
    mock_s3_client.ls.return_value = [
        {"Key": "path/chunk_0.parquet", "type": "file"},
        {"Key": "path/chunk_1.parquet", "type": "file"},
    ]
    mock_get_s3_client.return_value = mock_s3_client

    mock_kafka_producer = MagicMock()
    mock_kafka_producer_class.return_value = mock_kafka_producer

    test_data = pa.table({"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]})
    parquet_buffer = BytesIO()
    pq.write_table(test_data, parquet_buffer, compression="zstd")
    parquet_buffer.seek(0)

    mock_fs = MagicMock()
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=parquet_buffer)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_fs.open_input_file.return_value = mock_file
    mock_fs.delete_file = MagicMock()

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        producer.produce_to_kafka_from_s3()

    assert mock_kafka_producer.produce.call_count == 6
    mock_kafka_producer.flush.assert_called()
    assert mock_fs.delete_file.call_count == 2

    first_call_data = mock_kafka_producer.produce.call_args_list[0][1]["data"]
    assert first_call_data["team_id"] == team.id
    assert "properties" in first_call_data
    assert "id" in first_call_data["properties"]


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.FakeKafka")
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.get_s3_client")
def test_produce_to_kafka_from_s3_with_no_files(mock_get_s3_client, mock_kafka_producer_class, team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_s3_client = MagicMock()
    mock_s3_client.ls.side_effect = FileNotFoundError()
    mock_get_s3_client.return_value = mock_s3_client

    mock_kafka_producer = MagicMock()
    mock_kafka_producer_class.return_value = mock_kafka_producer

    mock_fs = MagicMock()
    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        producer.produce_to_kafka_from_s3()

    mock_kafka_producer.produce.assert_not_called()


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.FakeKafka")
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.get_s3_client")
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.capture_exception")
def test_produce_to_kafka_from_s3_kafka_failure(
    mock_capture_exception, mock_get_s3_client, mock_kafka_producer_class, team
):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_s3_client = MagicMock()
    mock_s3_client.ls.return_value = [{"Key": "path/chunk_0.parquet", "type": "file"}]
    mock_get_s3_client.return_value = mock_s3_client

    mock_kafka_producer = MagicMock()
    mock_kafka_producer.produce.side_effect = KafkaError("Kafka connection failed")
    mock_kafka_producer_class.return_value = mock_kafka_producer

    test_data = pa.table({"id": [1], "name": ["Alice"]})
    parquet_buffer = BytesIO()
    pq.write_table(test_data, parquet_buffer, compression="zstd")
    parquet_buffer.seek(0)

    mock_fs = MagicMock()
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=parquet_buffer)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_fs.open_input_file.return_value = mock_file
    mock_fs.delete_file = MagicMock()

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        producer.produce_to_kafka_from_s3()

    mock_capture_exception.assert_called_once()
    mock_fs.delete_file.assert_called_once()


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.FakeKafka")
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.get_s3_client")
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.capture_exception")
def test_produce_to_kafka_from_s3_s3_read_failure(
    mock_capture_exception, mock_get_s3_client, mock_kafka_producer_class, team
):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_s3_client = MagicMock()
    mock_s3_client.ls.return_value = [{"Key": "path/chunk_0.parquet", "type": "file"}]
    mock_get_s3_client.return_value = mock_s3_client

    mock_kafka_producer = MagicMock()
    mock_kafka_producer_class.return_value = mock_kafka_producer

    mock_fs = MagicMock()
    mock_fs.open_input_file.side_effect = Exception("S3 read failed")
    mock_fs.delete_file = MagicMock()

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        producer.produce_to_kafka_from_s3()

    mock_capture_exception.assert_called_once()
    mock_kafka_producer.produce.assert_not_called()
    mock_fs.delete_file.assert_called_once()


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.FakeKafka")
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.get_s3_client")
def test_produce_to_kafka_from_s3_with_large_batch(mock_get_s3_client, mock_kafka_producer_class, team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_s3_client = MagicMock()
    mock_s3_client.ls.return_value = [{"Key": "path/chunk_0.parquet", "type": "file"}]
    mock_get_s3_client.return_value = mock_s3_client

    mock_kafka_producer = MagicMock()
    mock_kafka_producer_class.return_value = mock_kafka_producer

    test_data = pa.table({"id": list(range(15000)), "value": [f"val_{i}" for i in range(15000)]})
    parquet_buffer = BytesIO()
    pq.write_table(test_data, parquet_buffer, compression="zstd")
    parquet_buffer.seek(0)

    mock_fs = MagicMock()
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=parquet_buffer)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_fs.open_input_file.return_value = mock_file
    mock_fs.delete_file = MagicMock()

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        producer.produce_to_kafka_from_s3()

    assert mock_kafka_producer.produce.call_count == 15000
    mock_kafka_producer.flush.assert_called()
    mock_fs.delete_file.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_write_chunk_for_cdp_producer(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_fs = MagicMock()
    test_data = pa.table({"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]})

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.write_table") as mock_write_table:
        with patch.object(producer, "_get_fs", return_value=mock_fs):
            producer.write_chunk_for_cdp_producer(chunk=5, table=test_data)

    mock_write_table.assert_called_once()
    call_args = mock_write_table.call_args
    assert call_args[0][0] == test_data
    assert "chunk_5.parquet" in call_args[0][1]
    assert call_args[1]["filesystem"] == mock_fs
    assert call_args[1]["compression"] == "zstd"
    assert call_args[1]["use_dictionary"] is True


@pytest.mark.django_db(transaction=True)
def test_write_chunk_for_cdp_producer_with_empty_table(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_fs = MagicMock()
    test_data = pa.table({"id": [], "name": []})

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.write_table") as mock_write_table:
        with patch.object(producer, "_get_fs", return_value=mock_fs):
            producer.write_chunk_for_cdp_producer(chunk=0, table=test_data)

    mock_write_table.assert_called_once()


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.get_s3_client")
def test_clear_s3_chunks_with_files(mock_get_s3_client, team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_s3_client = MagicMock()
    mock_s3_client.ls.return_value = [
        {"Key": "path/chunk_0.parquet", "type": "file"},
        {"Key": "path/chunk_1.parquet", "type": "file"},
    ]
    mock_get_s3_client.return_value = mock_s3_client

    mock_fs = MagicMock()
    mock_fs.delete_dir = MagicMock()

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        producer.clear_s3_chunks()

    mock_fs.delete_dir.assert_called_once()


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.get_s3_client")
def test_clear_s3_chunks_with_no_files(mock_get_s3_client, team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_s3_client = MagicMock()
    mock_s3_client.ls.side_effect = FileNotFoundError()
    mock_get_s3_client.return_value = mock_s3_client

    mock_fs = MagicMock()
    mock_fs.delete_dir = MagicMock()

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        producer.clear_s3_chunks()

    mock_fs.delete_dir.assert_not_called()


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.get_s3_client")
def test_clear_s3_chunks_handles_file_not_found_on_delete(mock_get_s3_client, team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    mock_s3_client = MagicMock()
    mock_s3_client.ls.return_value = [{"Key": "path/chunk_0.parquet", "type": "file"}]
    mock_get_s3_client.return_value = mock_s3_client

    mock_fs = MagicMock()
    mock_fs.delete_dir.side_effect = FileNotFoundError()

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        producer.clear_s3_chunks()


@pytest.mark.django_db(transaction=True)
def test_serialize_json_with_orjson_success(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    record = {"id": 1, "name": "Alice", "score": 95.5}
    result = producer._serialize_json(record)

    assert isinstance(result, bytes)
    assert json.loads(result) == record


@pytest.mark.django_db(transaction=True)
def test_serialize_json_fallback_to_standard_json(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    class CustomObject:
        def __str__(self):
            return "custom_value"

    record = {"id": 1, "custom": CustomObject()}

    with patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.orjson.dumps") as mock_orjson:
        mock_orjson.side_effect = TypeError("Cannot serialize")
        result = producer._serialize_json(record)

    assert isinstance(result, bytes)
    deserialized = json.loads(result)
    assert deserialized["id"] == "1"
    assert deserialized["custom"] == "custom_value"


@pytest.mark.django_db(transaction=True)
def test_serialize_json_fallback_with_stringify(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    class UnserializableKey:
        def __str__(self):
            return "key_1"

    class UnserializableValue:
        def __str__(self):
            return "value_1"

    record = {UnserializableKey(): UnserializableValue()}

    with patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.orjson.dumps") as mock_orjson:
        mock_orjson.side_effect = TypeError("Cannot serialize")
        result = producer._serialize_json(record)

    assert isinstance(result, bytes)
    deserialized = json.loads(result)
    assert deserialized["key_1"] == "value_1"


@pytest.mark.django_db(transaction=True)
def test_serialize_json_raises_on_non_dict_unsupported(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=MagicMock())

    class CompletelyUnserializable:
        pass

    record = CompletelyUnserializable()

    with patch("posthog.temporal.data_imports.pipelines.pipeline.cdp_producer.orjson.dumps") as mock_orjson:
        mock_orjson.side_effect = TypeError("Cannot serialize")
        with pytest.raises(ValueError, match="Could not serialize record to JSON"):
            producer._serialize_json(record)
