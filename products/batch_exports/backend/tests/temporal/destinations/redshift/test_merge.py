import pytest
from unittest.mock import AsyncMock, MagicMock

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import RedshiftClient


@pytest.mark.asyncio
@pytest.mark.parametrize("version_key", [("version",), ()])
@pytest.mark.parametrize("remove_duplicates", [True, False])
async def test_merge_with_optional_version_key(version_key: tuple[str, ...], remove_duplicates: bool) -> None:
    client = RedshiftClient(
        user="test", password="test", host="localhost", port=5439, database="test", ssl_mode="prefer"
    )
    cursor = AsyncMock()
    cursor.fetchone.return_value = ("snapshot isolation",)
    connection = MagicMock()
    connection.cursor.return_value.__aenter__.return_value = cursor
    client._connection = connection

    await client.amerge_tables(
        final_table_name="final",
        stage_table_name="stage",
        schema="test",
        merge_key=("id",),
        update_key=version_key,
        final_table_fields=[("id", "BIGINT"), ("version", "BIGINT")],
        remove_duplicates=remove_duplicates,
    )

    queries = [" ".join(call.args[0].as_string().split()) for call in cursor.execute.call_args_list]
    deletes = [query for query in queries if query.startswith("DELETE")]
    if version_key:
        assert len(deletes) == 1
        assert 'AND ("test"."stage"."version" < "final"."version")' in deletes[0]
    else:
        assert deletes == []
    merge = queries[-1]
    assert merge.startswith('MERGE INTO "test"."final"')
    assert 'ON "test"."final"."id" = "stage"."id"' in merge
    if remove_duplicates:
        assert merge.endswith("REMOVE DUPLICATES")
    else:
        assert "WHEN MATCHED THEN UPDATE SET" in merge
        assert "WHEN NOT MATCHED THEN INSERT" in merge
