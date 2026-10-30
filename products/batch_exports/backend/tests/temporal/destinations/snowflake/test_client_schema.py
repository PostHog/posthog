from collections.abc import AsyncIterator

import pytest
from unittest.mock import AsyncMock, patch

import pyarrow as pa
import pyarrow.parquet as pq

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeClient,
    SnowflakeIncompatibleSchemaError,
    SnowflakeTable,
)
from products.batch_exports.backend.temporal.pipeline.transformer import ParquetStreamTransformer, SchemaTransformer
from products.batch_exports.backend.tests.temporal.destinations.snowflake.utils import DESCRIBE_TABLE_METADATA


@pytest.fixture
def client() -> SnowflakeClient:
    return SnowflakeClient(
        user="test_user",
        account="test_account",
        warehouse="test_warehouse",
        database="test_db",
        schema="public",
        password="test_password",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_key", [None, "id", "version"])
@pytest.mark.parametrize("as_mapping", [False, True])
async def test_get_table_validates_keys_and_filters_columns(
    client: SnowflakeClient, missing_key: str | None, as_mapping: bool
) -> None:
    table = SnowflakeTable.from_arrow_schema(
        pa.schema([pa.field("id", pa.int64()), pa.field("version", pa.int64()), pa.field("missing", pa.string())]),  # type: ignore[arg-type]
        name='test"table',
        table_schema="public",
        database="test_db",
        primary_key=("id",),
        version_key=("version",),
    )
    rows = [
        ("ID", "NUMBER(38,0)", "COLUMN", "N"),
        ("VERSION", "NUMBER(38,0)", "COLUMN", "Y"),
        ("extra", "GEOGRAPHY", "COLUMN", "Y"),
    ]
    rows = [row for row in rows if row[0].lower() != missing_key]
    result_rows = (
        [{meta.name: value for meta, value in reversed(list(zip(DESCRIBE_TABLE_METADATA, row)))} for row in rows]
        if as_mapping
        else rows
    )
    with patch.object(
        client, "execute_async_query", new=AsyncMock(return_value=(result_rows, DESCRIBE_TABLE_METADATA))
    ) as execute:
        if missing_key is not None:
            with pytest.raises(SnowflakeIncompatibleSchemaError, match=f"'{missing_key}'"):
                await client.get_table(table)
        else:
            result = await client.get_table(table)
            assert [field.name for field in result.fields] == ["ID", "VERSION"]
            assert result["id"].data_type == pa.int64()
            assert result["id"].nullable is False
            assert result["version"].data_type == pa.int64()
            assert result["version"].nullable is True
    execute.assert_awaited_once_with('DESCRIBE TABLE "test""table"')


@pytest.mark.asyncio
@pytest.mark.parametrize("destination_type", ["UUID", "VARCHAR(16777216)"])
async def test_get_table_distinguishes_uuid_from_text_and_preserves_uuid_buffers(
    client: SnowflakeClient, destination_type: str
) -> None:
    batch = pa.record_batch(
        [pa.array([bytes.fromhex("00112233445546778899aabbccddeeff"), None], type=pa.uuid())],
        names=["Id"],
    )
    table = SnowflakeTable.from_arrow_schema(
        batch.schema, name="test_table", table_schema="public", database="test_db", primary_key=(), version_key=()
    )
    with patch.object(
        client,
        "execute_async_query",
        new=AsyncMock(return_value=([("Id", destination_type, "COLUMN", "Y")], DESCRIBE_TABLE_METADATA)),
    ) as execute:
        result = await client.get_table(table)
    execute.assert_awaited_once_with('DESCRIBE TABLE "test_table"')

    expected_type = pa.uuid() if destination_type == "UUID" else pa.string()
    assert result["Id"].data_type == expected_type
    assert result["Id"].snowflake_type_name == ("UUID" if destination_type == "UUID" else "TEXT")
    transformed = SchemaTransformer(table=result).cast_record_batch(batch)
    assert transformed.equals(batch)
    source_buffer = batch.column(0).buffers()[1]
    result_buffer = transformed.column(0).buffers()[1]
    assert source_buffer is not None
    assert result_buffer is not None
    assert result_buffer.address == source_buffer.address

    async def record_batches() -> AsyncIterator[pa.RecordBatch]:
        yield transformed

    chunks = [chunk.data async for chunk in ParquetStreamTransformer(compression="zstd").iter(record_batches())]
    parquet = pq.ParquetFile(pa.BufferReader(b"".join(chunks)))
    assert parquet.schema.column(0).logical_type.type == "UUID"
    assert parquet.read().equals(pa.Table.from_batches([batch]))
