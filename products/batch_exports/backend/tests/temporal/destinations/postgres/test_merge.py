import pytest
from unittest.mock import AsyncMock, MagicMock

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import PostgreSQLClient


@pytest.mark.asyncio
@pytest.mark.parametrize("version_key", [("version",), ()])
async def test_merge_with_optional_version_key(version_key: tuple[str, ...]) -> None:
    client = PostgreSQLClient(
        user="test", password="test", host="localhost", port=5432, database="test", ssl_mode="prefer"
    )
    cursor = AsyncMock()
    connection = MagicMock()
    connection.cursor.return_value.__aenter__.return_value = cursor
    client._connection = connection

    await client.amerge_mutable_tables(
        final_table_name="final",
        stage_table_name="stage",
        schema="test",
        merge_key=("id",),
        update_key=version_key,
        update_when_matched=[("id", "BIGINT"), ("version", "BIGINT")],
    )

    query = " ".join(cursor.execute.call_args.args[0].as_string().split())
    assert 'ON CONFLICT ("id") DO UPDATE SET "id" = EXCLUDED."id","version" = EXCLUDED."version"' in query
    if version_key:
        assert 'WHERE (EXCLUDED."version" > final."version")' in query
    else:
        assert "WHERE" not in query
