import pytest
from unittest.mock import AsyncMock, patch

import pyarrow as pa

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeClient,
    SnowflakeField,
    SnowflakeTable,
    SnowflakeType,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("version_key", [("version",), ()])
async def test_merge_with_optional_version_key(version_key: tuple[str, ...]) -> None:
    fields = tuple(SnowflakeField(name, SnowflakeType("INT", False), pa.int64(), False) for name in ("id", "version"))
    final = SnowflakeTable("final", fields, primary_key=("id",), version_key=version_key)
    stage = SnowflakeTable("stage", fields)
    client = SnowflakeClient(
        user="test", password="test", account="test", warehouse="test", database="test", schema="test"
    )

    assert final.is_mutable()
    with patch.object(client, "execute_async_query", new_callable=AsyncMock) as execute:
        await client.merge_into_final_from_stage(final, stage, timeout=60)

    query = " ".join(execute.call_args.args[0].split())
    assert 'ON final."id" = stage."id"' in query
    assert "WHEN NOT MATCHED THEN INSERT" in query
    if version_key:
        assert 'WHEN MATCHED AND (final."version" < stage."version") THEN UPDATE' in query
    else:
        assert "WHEN MATCHED THEN UPDATE" in query
