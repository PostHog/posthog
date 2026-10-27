import pytest
from unittest.mock import AsyncMock, patch

import pyarrow as pa

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeClient,
    SnowflakeField,
    SnowflakeTable,
    SnowflakeType,
)
from products.batch_exports.backend.temporal.utils import JsonType


@pytest.mark.asyncio
@pytest.mark.parametrize("versioned", [True, False])
@pytest.mark.parametrize(
    "key,quoted_key,version,quoted_version",
    [
        ("id", '"id"', "version", '"version"'),
        ('key"name', '"key""name"', 'version"name', '"version""name"'),
    ],
)
async def test_merge_with_optional_version_key(
    versioned: bool, key: str, quoted_key: str, version: str, quoted_version: str
) -> None:
    fields = tuple(SnowflakeField(name, SnowflakeType("INT", False), pa.int64(), False) for name in (key, version))
    final = SnowflakeTable("final", fields, primary_key=(key,), version_key=(version,) if versioned else ())
    stage = SnowflakeTable("stage", fields)
    client = SnowflakeClient(
        user="test", password="test", account="test", warehouse="test", database="test", schema="test"
    )

    assert final.is_mutable()
    with patch.object(client, "execute_async_query", new_callable=AsyncMock) as execute:
        await client.merge_into_final_from_stage(final, stage, timeout=60)

    query = " ".join(execute.call_args.args[0].split())
    assert f"ON final.{quoted_key} = stage.{quoted_key}" in query
    assert (
        f"UPDATE SET final.{quoted_key} = stage.{quoted_key}, final.{quoted_version} = stage.{quoted_version}" in query
    )
    assert f"WHEN NOT MATCHED THEN INSERT ({quoted_key}, {quoted_version})" in query
    assert f"VALUES (stage.{quoted_key}, stage.{quoted_version})" in query
    if versioned:
        assert f"WHEN MATCHED AND (final.{quoted_version} < stage.{quoted_version}) THEN UPDATE" in query
    else:
        assert "WHEN MATCHED THEN UPDATE" in query


@pytest.mark.asyncio
@pytest.mark.parametrize("create", [True, False])
async def test_staging_quotes_column_names(create: bool) -> None:
    table = SnowflakeTable(
        "stage",
        (
            SnowflakeField('key"name', SnowflakeType("INT", False), pa.int64(), False),
            SnowflakeField('json"data', SnowflakeType("VARIANT", False), JsonType(), True),
        ),
    )
    client = SnowflakeClient(
        user="test", password="test", account="test", warehouse="test", database="test", schema="test"
    )
    with patch.object(client, "execute_async_query", new_callable=AsyncMock, return_value=([], None)) as execute:
        if create:
            await client.create_table(table)
        else:
            await client.copy_loaded_files_to_snowflake_table(table, timeout=60)

    query = " ".join(execute.call_args.args[0].split())
    if create:
        assert 'CREATE TABLE IF NOT EXISTS "stage" ( "key""name" INT, "json""data" VARIANT )' in query
    else:
        assert 'COPY INTO "stage" ("key""name", "json""data")' in query
        assert 'SELECT $1:"key""name", PARSE_JSON($1:"json""data", \'d\')' in query
