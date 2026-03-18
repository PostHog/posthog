from __future__ import annotations

import uuid
import functools
import contextlib

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.test import override_settings

import orjson
import pyarrow as pa
import aioboto3
import pyarrow.parquet as pq
from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager


def _table_to_parquet_bytes(table: pa.Table) -> bytes:
    buf = pa.BufferOutputStream()
    pq.write_table(table, buf)
    return buf.getvalue().to_pybytes()


def _make_webhook_parquet_bytes(payloads: list[dict], team_id: int = 1, schema_id: str = "test-schema") -> bytes:
    table = pa.table(
        {
            "team_id": [team_id] * len(payloads),
            "schema_id": [schema_id] * len(payloads),
            "payload_json": [orjson.dumps(p).decode() for p in payloads],
        }
    )
    return _table_to_parquet_bytes(table)


BUCKET_NAME = "test-webhook-s3"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


def _make_inputs(**overrides) -> MagicMock:
    inputs = MagicMock()
    inputs.team_id = overrides.get("team_id", 1)
    inputs.schema_id = overrides.get("schema_id", str(uuid.uuid4()))
    inputs.reset_pipeline = overrides.get("reset_pipeline", False)
    return inputs


def _make_manager(**input_overrides) -> WebhookSourceManager:
    inputs = _make_inputs(**input_overrides)
    logger = AsyncMock()
    return WebhookSourceManager(inputs=inputs, logger=logger)


@contextlib.contextmanager
def _mock_s3_context(mock_s3: AsyncMock):
    """Patch aget_s3_client to yield a mock async context manager wrapping mock_s3."""
    with patch("posthog.temporal.data_imports.sources.common.webhook_s3.aget_s3_client") as mock_get_s3:
        mock_get_s3.return_value.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_get_s3.return_value.__aexit__ = AsyncMock(return_value=False)
        yield mock_get_s3


@pytest.mark.asyncio
class TestWebhookSourceManager:
    def test_get_webhook_s3_prefix(self):
        manager = _make_manager(team_id=42, schema_id="schema-abc")

        with patch("posthog.temporal.data_imports.sources.common.webhook_s3.settings") as mock_settings:
            mock_settings.DATAWAREHOUSE_BUCKET = "my-bucket"
            result = manager._get_webhook_s3_prefix()

        assert result == "s3://my-bucket/source_webhook_producer/42/schema-abc"

    @parameterized.expand(
        [
            ("with_protocol", "s3://bucket/key/file.parquet", "bucket/key/file.parquet"),
            ("without_protocol", "bucket/key/file.parquet", "bucket/key/file.parquet"),
            ("empty_string", "", ""),
        ]
    )
    def test_strip_s3_protocol(self, _name, input_path, expected):
        manager = _make_manager()
        assert manager._strip_s3_protocol(input_path) == expected

    def test_transform_webhook_table_parses_json_payloads(self):
        manager = _make_manager()
        payloads = [
            {"id": "1", "name": "alice"},
            {"id": "2", "name": "bob"},
        ]
        source_table = pa.table({"payload_json": [orjson.dumps(p).decode() for p in payloads]})

        result = manager._transform_webhook_table(source_table)

        assert result.num_rows == 2
        assert result.column("id").to_pylist() == ["1", "2"]
        assert result.column("name").to_pylist() == ["alice", "bob"]

    def test_transform_webhook_table_handles_nested_json(self):
        manager = _make_manager()
        payloads = [{"event": "click", "properties": {"url": "https://example.com"}}]
        source_table = pa.table({"payload_json": [orjson.dumps(p).decode() for p in payloads]})

        result = manager._transform_webhook_table(source_table)

        assert result.num_rows == 1
        assert result.column("event").to_pylist() == ["click"]

    async def test_webhook_enabled_returns_false_when_flag_disabled(self):
        manager = _make_manager()

        with patch.object(manager, "_is_webhook_feature_flag_enabled", return_value=False):
            assert await manager.webhook_enabled() is False

    @parameterized.expand(
        [
            ("no_hog_function", False, True, True, False, False),
            ("not_incremental", True, False, True, False, False),
            ("initial_sync_not_complete", True, True, False, False, False),
            ("reset_pipeline_true", True, True, True, True, False),
            ("all_conditions_met", True, True, True, False, True),
        ]
    )
    async def test_webhook_enabled_conditions(
        self,
        _name,
        has_webhook_function,
        is_incremental,
        initial_sync_complete,
        reset_pipeline,
        expected,
    ):
        manager = _make_manager(reset_pipeline=reset_pipeline)

        mock_schema = MagicMock()
        mock_schema.is_incremental = is_incremental
        mock_schema.initial_sync_complete = initial_sync_complete

        call_count = 0

        def mock_db_sync_to_async(fn):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return AsyncMock(return_value=mock_schema)
            return AsyncMock(return_value=has_webhook_function)

        with (
            patch.object(manager, "_is_webhook_feature_flag_enabled", return_value=True),
            patch(
                "posthog.temporal.data_imports.sources.common.webhook_s3.database_sync_to_async_pool",
                side_effect=mock_db_sync_to_async,
            ),
        ):
            assert await manager.webhook_enabled() is expected

    async def test_list_parquet_files_filters_correctly(self):
        manager = _make_manager()

        mock_ls_result = [
            {"Key": "bucket/path/file1.parquet", "type": "file"},
            {"Key": "bucket/path/file2.parquet", "type": "file"},
            {"Key": "bucket/path/subdir", "type": "directory"},
            {"Key": "bucket/path/file3.json", "type": "file"},
        ]

        mock_s3 = AsyncMock()
        mock_s3._ls = AsyncMock(return_value=mock_ls_result)

        with _mock_s3_context(mock_s3):
            result = await manager._list_webhook_parquet_files()

        assert result == [
            "s3://bucket/path/file1.parquet",
            "s3://bucket/path/file2.parquet",
        ]

    async def test_list_parquet_files_returns_empty_on_not_found(self):
        manager = _make_manager()

        mock_s3 = AsyncMock()
        mock_s3._ls = AsyncMock(side_effect=FileNotFoundError)

        with _mock_s3_context(mock_s3):
            result = await manager._list_webhook_parquet_files()

        assert result == []

    async def test_list_parquet_files_handles_dict_response(self):
        manager = _make_manager()

        mock_ls_result = {
            "file1": {"Key": "bucket/path/file1.parquet", "type": "file"},
        }

        mock_s3 = AsyncMock()
        mock_s3._ls = AsyncMock(return_value=mock_ls_result)

        with _mock_s3_context(mock_s3):
            result = await manager._list_webhook_parquet_files()

        assert result == ["s3://bucket/path/file1.parquet"]

    async def test_validate_webhook_table_keeps_matching_rows(self):
        manager = _make_manager(team_id=1, schema_id="schema-abc")
        table = pa.table(
            {
                "team_id": [1, 1],
                "schema_id": ["schema-abc", "schema-abc"],
                "payload_json": ['{"id": "1"}', '{"id": "2"}'],
            }
        )

        result = await manager._validate_webhook_table(table)

        assert result.num_rows == 2

    @parameterized.expand(
        [
            ("wrong_team_id", 999, "schema-abc"),
            ("wrong_schema_id", 1, "wrong-schema"),
            ("both_wrong", 999, "wrong-schema"),
        ]
    )
    async def test_validate_webhook_table_filters_mismatched_rows(self, _name, row_team_id, row_schema_id):
        manager = _make_manager(team_id=1, schema_id="schema-abc")
        table = pa.table(
            {
                "team_id": [row_team_id],
                "schema_id": [row_schema_id],
                "payload_json": ['{"id": "1"}'],
            }
        )

        result = await manager._validate_webhook_table(table)

        assert result.num_rows == 0

    async def test_validate_webhook_table_partial_match(self):
        manager = _make_manager(team_id=1, schema_id="schema-abc")
        table = pa.table(
            {
                "team_id": [1, 999, 1],
                "schema_id": ["schema-abc", "schema-abc", "wrong"],
                "payload_json": ['{"id": "1"}', '{"id": "2"}', '{"id": "3"}'],
            }
        )

        result = await manager._validate_webhook_table(table)

        assert result.num_rows == 1
        assert result.column("payload_json").to_pylist() == ['{"id": "1"}']

    async def test_get_items_yields_transformed_tables_and_deletes_files(self):
        schema_id = "test-schema"
        manager = _make_manager(team_id=1, schema_id=schema_id)

        payloads = [{"id": "1", "value": "a"}]
        parquet_bytes = _make_webhook_parquet_bytes(payloads, team_id=1, schema_id=schema_id)

        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=parquet_bytes)
        mock_s3 = AsyncMock()
        mock_s3.open_async = AsyncMock(return_value=AsyncMock())
        mock_s3.open_async.return_value.__aenter__ = AsyncMock(return_value=mock_file)
        mock_s3.open_async.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_s3._rm = AsyncMock()

        with (
            patch.object(manager, "_list_webhook_parquet_files", return_value=["s3://bucket/file.parquet"]),
            _mock_s3_context(mock_s3),
        ):
            tables = [table async for table in manager.get_items()]

        assert len(tables) == 1
        assert tables[0].column("id").to_pylist() == ["1"]
        assert tables[0].column("value").to_pylist() == ["a"]
        mock_s3._rm.assert_awaited_once_with("bucket/file.parquet")

    async def test_get_items_skips_file_when_all_rows_fail_validation(self):
        schema_id = "test-schema"
        manager = _make_manager(team_id=1, schema_id=schema_id)

        payloads = [{"id": "1"}]
        parquet_bytes = _make_webhook_parquet_bytes(payloads, team_id=999, schema_id="wrong")

        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=parquet_bytes)
        mock_s3 = AsyncMock()
        mock_s3.open_async = AsyncMock(return_value=AsyncMock())
        mock_s3.open_async.return_value.__aenter__ = AsyncMock(return_value=mock_file)
        mock_s3.open_async.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_s3._rm = AsyncMock()

        with (
            patch.object(manager, "_list_webhook_parquet_files", return_value=["s3://bucket/file.parquet"]),
            _mock_s3_context(mock_s3),
        ):
            tables = [table async for table in manager.get_items()]

        assert len(tables) == 0
        mock_s3._rm.assert_awaited_once_with("bucket/file.parquet")

    async def test_get_items_applies_table_transformer(self):
        schema_id = "test-schema"
        manager = _make_manager(team_id=1, schema_id=schema_id)

        payloads = [{"id": "1", "count": 5}]
        parquet_bytes = _make_webhook_parquet_bytes(payloads, team_id=1, schema_id=schema_id)

        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=parquet_bytes)
        mock_s3 = AsyncMock()
        mock_s3.open_async = AsyncMock(return_value=AsyncMock())
        mock_s3.open_async.return_value.__aenter__ = AsyncMock(return_value=mock_file)
        mock_s3.open_async.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_s3._rm = AsyncMock()

        transformer = MagicMock(side_effect=lambda t: t.select(["id"]))

        with (
            patch.object(manager, "_list_webhook_parquet_files", return_value=["s3://bucket/file.parquet"]),
            _mock_s3_context(mock_s3),
        ):
            tables = [table async for table in manager.get_items(table_transformer=transformer)]

        assert len(tables) == 1
        assert tables[0].column_names == ["id"]
        transformer.assert_called_once()

    async def test_get_items_yields_nothing_when_no_files(self):
        manager = _make_manager()

        mock_s3 = AsyncMock()

        with (
            patch.object(manager, "_list_webhook_parquet_files", return_value=[]),
            _mock_s3_context(mock_s3),
        ):
            tables = [table async for table in manager.get_items()]

        assert tables == []

    async def test_feature_flag_returns_false_when_team_not_found(self):
        from posthog.models import Team

        manager = _make_manager(team_id=999)

        with patch(
            "posthog.temporal.data_imports.sources.common.webhook_s3.database_sync_to_async_pool",
            return_value=AsyncMock(side_effect=Team.DoesNotExist),
        ):
            result = await manager._is_webhook_feature_flag_enabled()

        assert result is False

    async def test_feature_flag_returns_false_on_analytics_exception(self):
        manager = _make_manager()
        mock_team = MagicMock()
        mock_team.uuid = uuid.uuid4()
        mock_team.organization_id = uuid.uuid4()
        mock_team.id = 1

        call_count = 0

        async def mock_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_team
            raise Exception("PostHog analytics error")

        with (
            patch(
                "posthog.temporal.data_imports.sources.common.webhook_s3.database_sync_to_async_pool",
                return_value=mock_side_effect,
            ),
            patch("posthog.temporal.data_imports.sources.common.webhook_s3.capture_exception"),
        ):
            result = await manager._is_webhook_feature_flag_enabled()

        assert result is False

    async def test_feature_flag_returns_true_when_enabled(self):
        manager = _make_manager()
        mock_team = MagicMock()
        mock_team.uuid = uuid.uuid4()
        mock_team.organization_id = uuid.uuid4()
        mock_team.id = 1

        call_count = 0

        async def mock_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_team
            return True

        with patch(
            "posthog.temporal.data_imports.sources.common.webhook_s3.database_sync_to_async_pool",
            return_value=mock_side_effect,
        ):
            result = await manager._is_webhook_feature_flag_enabled()

        assert result is True


# -- Integration tests using MinIO --


async def _upload_parquet_to_minio(
    minio_client, key: str, payloads: list[dict], team_id: int = 99, schema_id: str = "test-schema"
) -> None:
    parquet_bytes = _make_webhook_parquet_bytes(payloads, team_id=team_id, schema_id=schema_id)
    await minio_client.put_object(Bucket=BUCKET_NAME, Key=key, Body=parquet_bytes)


async def _minio_key_exists(minio_client, key: str) -> bool:
    try:
        await minio_client.head_object(Bucket=BUCKET_NAME, Key=key)
        return True
    except minio_client.exceptions.ClientError:
        return False


@pytest.fixture
async def minio_client():
    async with create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as client:
        try:
            await client.head_bucket(Bucket=BUCKET_NAME)
        except Exception:
            await client.create_bucket(Bucket=BUCKET_NAME)

        yield client

        # Clean up all objects in the bucket after each test
        response = await client.list_objects_v2(Bucket=BUCKET_NAME)
        for obj in response.get("Contents", []):
            await client.delete_object(Bucket=BUCKET_NAME, Key=obj["Key"])


@pytest.fixture
def minio_settings():
    with override_settings(
        DATAWAREHOUSE_BUCKET=BUCKET_NAME,
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        USE_LOCAL_SETUP=True,
    ):
        yield


@pytest.mark.asyncio
@pytest.mark.usefixtures("minio_settings")
class TestWebhookSourceManagerWithMinIO:
    async def test_list_parquet_files_from_s3(self, minio_client):
        team_id = 99
        schema_id = "test-schema-list"
        prefix = f"source_webhook_producer/{team_id}/{schema_id}"

        await _upload_parquet_to_minio(
            minio_client, f"{prefix}/batch1.parquet", [{"id": "1"}], team_id=team_id, schema_id=schema_id
        )
        await _upload_parquet_to_minio(
            minio_client, f"{prefix}/batch2.parquet", [{"id": "2"}], team_id=team_id, schema_id=schema_id
        )

        manager = _make_manager(team_id=team_id, schema_id=schema_id)
        files = await manager._list_webhook_parquet_files()

        assert len(files) == 2
        assert all(f.endswith(".parquet") for f in files)

    async def test_list_parquet_files_returns_empty_when_prefix_missing(self, minio_client):
        manager = _make_manager(team_id=12345, schema_id="nonexistent")
        files = await manager._list_webhook_parquet_files()

        assert files == []

    async def test_get_items_reads_and_deletes_files(self, minio_client):
        team_id = 99
        schema_id = "test-schema-items"
        prefix = f"source_webhook_producer/{team_id}/{schema_id}"
        key = f"{prefix}/batch.parquet"

        payloads = [
            {"id": "1", "name": "alice"},
            {"id": "2", "name": "bob"},
        ]
        await _upload_parquet_to_minio(minio_client, key, payloads, team_id=team_id, schema_id=schema_id)

        manager = _make_manager(team_id=team_id, schema_id=schema_id)
        tables = [table async for table in manager.get_items()]

        assert len(tables) == 1
        assert tables[0].num_rows == 2
        assert tables[0].column("id").to_pylist() == ["1", "2"]
        assert tables[0].column("name").to_pylist() == ["alice", "bob"]

        # File should be deleted after reading
        assert not await _minio_key_exists(minio_client, key)

    async def test_get_items_applies_transformer(self, minio_client):
        team_id = 99
        schema_id = "test-schema-transform"
        prefix = f"source_webhook_producer/{team_id}/{schema_id}"

        await _upload_parquet_to_minio(
            minio_client,
            f"{prefix}/batch.parquet",
            [{"id": "1", "extra": "drop_me"}],
            team_id=team_id,
            schema_id=schema_id,
        )

        manager = _make_manager(team_id=team_id, schema_id=schema_id)
        tables = [table async for table in manager.get_items(table_transformer=lambda t: t.select(["id"]))]

        assert len(tables) == 1
        assert tables[0].column_names == ["id"]

    async def test_get_items_processes_multiple_files_in_order(self, minio_client):
        team_id = 99
        schema_id = "test-schema-multi"
        prefix = f"source_webhook_producer/{team_id}/{schema_id}"

        await _upload_parquet_to_minio(
            minio_client, f"{prefix}/batch_a.parquet", [{"id": "a"}], team_id=team_id, schema_id=schema_id
        )
        await _upload_parquet_to_minio(
            minio_client, f"{prefix}/batch_b.parquet", [{"id": "b"}], team_id=team_id, schema_id=schema_id
        )

        manager = _make_manager(team_id=team_id, schema_id=schema_id)
        tables = [table async for table in manager.get_items()]

        assert len(tables) == 2
        ids = sorted([t.column("id").to_pylist()[0] for t in tables])  # type: ignore
        assert ids == ["a", "b"]

        # Both files should be deleted
        response = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
        assert response.get("Contents", []) == []

    async def test_get_items_skips_file_with_wrong_team_id(self, minio_client):
        team_id = 99
        schema_id = "test-schema-validate"
        prefix = f"source_webhook_producer/{team_id}/{schema_id}"
        key = f"{prefix}/batch.parquet"

        await _upload_parquet_to_minio(minio_client, key, [{"id": "1"}], team_id=999, schema_id=schema_id)

        manager = _make_manager(team_id=team_id, schema_id=schema_id)
        tables = [table async for table in manager.get_items()]

        assert len(tables) == 0
        assert not await _minio_key_exists(minio_client, key)
