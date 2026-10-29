import pytest
from unittest.mock import AsyncMock, patch

import pyarrow as pa

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeClient,
    SnowflakeIncompatibleSchemaError,
    SnowflakeTable,
)


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
async def test_get_table_validates_keys_and_filters_columns(client: SnowflakeClient, missing_key: str | None) -> None:
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
    with patch.object(client, "execute_async_query", new=AsyncMock(return_value=(rows, []))) as execute:
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
