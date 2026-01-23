from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

import snappy
from botocore.client import Config
from parameterized import parameterized

from posthog.settings.session_replay_v2 import (
    SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
    SESSION_RECORDING_V2_S3_BUCKET,
    SESSION_RECORDING_V2_S3_ENDPOINT,
    SESSION_RECORDING_V2_S3_REGION,
    SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
)
from posthog.storage.recordings.block_storage import (
    ClearTextBlockStorage,
    EncryptedBlockStorage,
    cleartext_block_storage,
)
from posthog.storage.recordings.errors import BlockFetchError, RecordingDeletedError

TEST_BUCKET = "test_session_recording_v2_bucket"


class AsyncContextManager:
    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc, traceback):
        pass


class TestAsyncSessionRecordingV2Storage(APIBaseTest):
    def teardown_method(self, method) -> None:
        pass

    @patch("posthog.storage.recordings.block_storage.aioboto3")
    async def test_client_constructor_uses_correct_settings(self, patched_aioboto3) -> None:
        # Reset the global client to ensure we test client creation
        import posthog.storage.recordings.block_storage as storage_module

        client_mock = MagicMock(AsyncContextManager)
        patched_aioboto3.Session.return_value.client = client_mock

        async with storage_module.cleartext_block_storage() as storage:
            assert patched_aioboto3.Session.call_count == 1
            assert client_mock.call_count == 1

            call_args = client_mock.call_args[0]
            call_kwargs = client_mock.call_args[1]

            assert call_args == ("s3",)
            assert call_kwargs["endpoint_url"] == SESSION_RECORDING_V2_S3_ENDPOINT
            assert call_kwargs["aws_access_key_id"] == SESSION_RECORDING_V2_S3_ACCESS_KEY_ID
            assert call_kwargs["aws_secret_access_key"] == SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY
            assert call_kwargs["region_name"] == SESSION_RECORDING_V2_S3_REGION

            config = call_kwargs["config"]
            assert isinstance(config, Config)
            assert config.signature_version == "s3v4"  # type: ignore[attr-defined]
            assert config.connect_timeout == 1  # type: ignore[attr-defined]
            assert config.retries == {"max_attempts": 1}  # type: ignore[attr-defined]

            assert isinstance(storage, ClearTextBlockStorage)
            assert storage.bucket == SESSION_RECORDING_V2_S3_BUCKET

    @parameterized.expand(
        [
            ({"SESSION_RECORDING_V2_S3_BUCKET": ""},),
            ({"SESSION_RECORDING_V2_S3_ENDPOINT": ""},),
            ({"SESSION_RECORDING_V2_S3_REGION": ""},),
            (
                {
                    "SESSION_RECORDING_V2_S3_BUCKET": "",
                    "SESSION_RECORDING_V2_S3_ENDPOINT": "",
                    "SESSION_RECORDING_V2_S3_REGION": "",
                },
            ),
        ]
    )
    @patch("posthog.storage.recordings.block_storage.aioboto3")
    async def test_throws_runtimeerror_if_required_settings_missing(self, settings_override, patched_aioboto3) -> None:
        with self.settings(**settings_override):
            client_mock = MagicMock(AsyncContextManager)
            patched_aioboto3.Session.return_value.client = client_mock

            with self.assertRaises(RuntimeError) as _:
                async with cleartext_block_storage() as _:
                    pass

            client_mock.assert_not_called()

    async def test_fetch_block_success(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = "test data"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = ClearTextBlockStorage(mock_client, TEST_BUCKET)

        block_url = f"s3://bucket/key1?range=bytes=0-{len(compressed_data) - 1}"
        result = await storage.fetch_decompressed_block(block_url)

        assert result == test_data
        mock_client.get_object.assert_called_with(
            Bucket=TEST_BUCKET, Key="key1", Range=f"bytes=0-{len(compressed_data) - 1}"
        )

    @parameterized.expand(
        [
            ("s3://bucket/key1", "Invalid byte range"),
            ("s3://bucket/key1?range=invalid", "Invalid byte range"),
        ]
    )
    async def test_fetch_block_invalid_url(self, invalid_url, expected_error):
        storage = ClearTextBlockStorage(AsyncMock(), TEST_BUCKET)

        with self.assertRaises(BlockFetchError) as cm:
            await storage.fetch_decompressed_block(invalid_url)
        assert expected_error in str(cm.exception)

    async def test_fetch_block_content_not_found(self):
        mock_client = AsyncMock()
        mock_client.get_object.return_value = {"Body": MagicMock(read=AsyncMock(return_value=None))}
        storage = ClearTextBlockStorage(mock_client, TEST_BUCKET)

        with self.assertRaises(BlockFetchError) as cm:
            await storage.fetch_decompressed_block("s3://bucket/key1?range=bytes=0-100")
        assert "Block content not found" in str(cm.exception)

    async def test_fetch_block_wrong_content_length(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        mock_body.read.return_value = b"short"  # Only 5 bytes
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = ClearTextBlockStorage(mock_client, TEST_BUCKET)

        with self.assertRaises(BlockFetchError) as cm:
            await storage.fetch_decompressed_block("s3://bucket/key1?range=bytes=0-100")
        assert "Unexpected data length" in str(cm.exception)

    async def test_fetch_compressed_block_success(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = "test data"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = ClearTextBlockStorage(mock_client, TEST_BUCKET)

        block_url = f"s3://bucket/key1?range=bytes=0-{len(compressed_data) - 1}"
        result = await storage.fetch_compressed_block(block_url)

        assert result == compressed_data
        mock_client.get_object.assert_called_with(
            Bucket=TEST_BUCKET, Key="key1", Range=f"bytes=0-{len(compressed_data) - 1}"
        )

    async def test_fetch_compressed_block_returns_compressed_data(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = "test data for compression"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = ClearTextBlockStorage(mock_client, TEST_BUCKET)

        block_url = f"s3://bucket/key1?range=bytes=0-{len(compressed_data) - 1}"
        result = await storage.fetch_compressed_block(block_url)

        # Verify it returns compressed bytes, not decompressed string
        assert isinstance(result, bytes)
        assert result == compressed_data
        assert result != test_data.encode("utf-8")  # Should NOT be decompressed


class MockResponse:
    def __init__(self, status: int, data: bytes | dict | None = None):
        self.status = status
        self._data = data

    async def read(self) -> bytes:
        if isinstance(self._data, bytes):
            return self._data
        return b""

    async def json(self) -> dict:
        if isinstance(self._data, dict):
            return self._data
        return {}

    def raise_for_status(self):
        if self.status >= 400:
            raise Exception(f"HTTP {self.status}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


def create_mock_session(method: str, response: MockResponse):
    """Create a mock aiohttp session with a properly configured async context manager."""
    mock_session = MagicMock()
    mock_method = MagicMock(return_value=response)
    setattr(mock_session, method, mock_method)
    return mock_session, mock_method


class TestEncryptedBlockStorage(APIBaseTest):
    def teardown_method(self, method) -> None:
        pass

    async def test_fetch_compressed_block_success(self):
        compressed_data = snappy.compress(b"test data")
        mock_session, mock_get = create_mock_session("get", MockResponse(200, compressed_data))

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        result = await storage.fetch_compressed_block(
            "s3://bucket/key1?range=bytes=0-100", session_id="session-123", team_id=1
        )

        assert result == compressed_data
        mock_get.assert_called_once_with(
            "http://localhost:8000/api/projects/1/recordings/session-123/block",
            params={"key": "key1", "start": 0, "end": 100},
        )

    async def test_fetch_compressed_block_404_raises_fetch_error(self):
        mock_session, _ = create_mock_session("get", MockResponse(404))

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        with self.assertRaises(BlockFetchError) as cm:
            await storage.fetch_compressed_block(
                "s3://bucket/key1?range=bytes=0-100", session_id="session-123", team_id=1
            )
        assert "Block not found" in str(cm.exception)

    async def test_fetch_compressed_block_410_raises_deleted_error(self):
        deleted_at = 1700000000
        mock_session, _ = create_mock_session(
            "get", MockResponse(410, {"error": "Recording has been deleted", "deleted_at": deleted_at})
        )

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        with self.assertRaises(RecordingDeletedError) as cm:
            await storage.fetch_compressed_block(
                "s3://bucket/key1?range=bytes=0-100", session_id="session-123", team_id=1
            )
        assert "Recording has been deleted" in str(cm.exception)
        assert cm.exception.deleted_at == deleted_at

    async def test_fetch_compressed_block_410_raises_deleted_error_with_none_deleted_at(self):
        mock_session, _ = create_mock_session(
            "get", MockResponse(410, {"error": "Recording has been deleted", "deleted_at": None})
        )

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        with self.assertRaises(RecordingDeletedError) as cm:
            await storage.fetch_compressed_block(
                "s3://bucket/key1?range=bytes=0-100", session_id="session-123", team_id=1
            )
        assert "Recording has been deleted" in str(cm.exception)
        assert cm.exception.deleted_at is None

    async def test_fetch_block_410_raises_deleted_error(self):
        deleted_at = 1700000000
        mock_session, _ = create_mock_session(
            "get", MockResponse(410, {"error": "Recording has been deleted", "deleted_at": deleted_at})
        )

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        with self.assertRaises(RecordingDeletedError) as cm:
            await storage.fetch_decompressed_block(
                "s3://bucket/key1?range=bytes=0-100", session_id="session-123", team_id=1
            )
        assert "Recording has been deleted" in str(cm.exception)
        assert cm.exception.deleted_at == deleted_at

    async def test_fetch_block_410_raises_deleted_error_with_none_deleted_at(self):
        mock_session, _ = create_mock_session(
            "get", MockResponse(410, {"error": "Recording has been deleted", "deleted_at": None})
        )

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        with self.assertRaises(RecordingDeletedError) as cm:
            await storage.fetch_decompressed_block(
                "s3://bucket/key1?range=bytes=0-100", session_id="session-123", team_id=1
            )
        assert "Recording has been deleted" in str(cm.exception)
        assert cm.exception.deleted_at is None

    async def test_delete_recording_success(self):
        mock_session, mock_delete = create_mock_session("delete", MockResponse(200, {"status": "deleted"}))

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        result = await storage.delete_recording(session_id="session-123", team_id=1)

        assert result is True
        mock_delete.assert_called_once_with("http://localhost:8000/api/projects/1/recordings/session-123")

    async def test_delete_recording_404_raises_fetch_error(self):
        mock_session, _ = create_mock_session("delete", MockResponse(404))

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        with self.assertRaises(BlockFetchError) as cm:
            await storage.delete_recording(session_id="session-123", team_id=1)
        assert "Recording key not found" in str(cm.exception)

    async def test_delete_recording_410_raises_deleted_error(self):
        deleted_at = 1700000000
        mock_session, _ = create_mock_session(
            "delete", MockResponse(410, {"error": "Recording has already been deleted", "deleted_at": deleted_at})
        )

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        with self.assertRaises(RecordingDeletedError) as cm:
            await storage.delete_recording(session_id="session-123", team_id=1)
        assert "Recording has already been deleted" in str(cm.exception)
        assert cm.exception.deleted_at == deleted_at

    async def test_delete_recording_410_raises_deleted_error_with_none_deleted_at(self):
        mock_session, _ = create_mock_session(
            "delete", MockResponse(410, {"error": "Recording has already been deleted", "deleted_at": None})
        )

        storage = EncryptedBlockStorage(mock_session, "http://localhost:8000")

        with self.assertRaises(RecordingDeletedError) as cm:
            await storage.delete_recording(session_id="session-123", team_id=1)
        assert "Recording has already been deleted" in str(cm.exception)
        assert cm.exception.deleted_at is None
