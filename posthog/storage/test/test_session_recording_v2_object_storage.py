from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

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
from posthog.storage.session_recording_v2_object_storage import (
    AsyncSessionRecordingV2ObjectStorage,
    BlockFetchError,
    SessionRecordingV2ObjectStorage,
    UnavailableSessionRecordingV2ObjectStorage,
    async_client,
    client,
)

TEST_BUCKET = "test_session_recording_v2_bucket"


class TestSessionRecordingV2Storage(APIBaseTest):
    def teardown_method(self, method) -> None:
        pass

    @patch("posthog.storage.session_recording_v2_object_storage.boto3_client")
    def test_client_constructor_uses_correct_settings(self, patched_boto3_client) -> None:
        # Reset the global client to ensure we test client creation
        import posthog.storage.session_recording_v2_object_storage as storage_module

        storage_module._client = UnavailableSessionRecordingV2ObjectStorage()

        storage_client = client()

        # Check that boto3_client was called once
        assert patched_boto3_client.call_count == 1
        call_args = patched_boto3_client.call_args[0]
        call_kwargs = patched_boto3_client.call_args[1]

        # Check positional args
        assert call_args == ("s3",)

        # Check kwargs except config
        assert call_kwargs["endpoint_url"] == SESSION_RECORDING_V2_S3_ENDPOINT
        assert call_kwargs["aws_access_key_id"] == SESSION_RECORDING_V2_S3_ACCESS_KEY_ID
        assert call_kwargs["aws_secret_access_key"] == SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY
        assert call_kwargs["region_name"] == SESSION_RECORDING_V2_S3_REGION

        # Check config parameters separately
        config = call_kwargs["config"]
        assert isinstance(config, Config)
        assert config.signature_version == "s3v4"  # type: ignore[attr-defined]
        assert config.connect_timeout == 1  # type: ignore[attr-defined]
        assert config.retries == {"max_attempts": 1}  # type: ignore[attr-defined]

        # Check the returned client
        assert isinstance(storage_client, SessionRecordingV2ObjectStorage)
        assert storage_client.bucket == SESSION_RECORDING_V2_S3_BUCKET

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
    @patch("posthog.storage.session_recording_v2_object_storage.boto3_client")
    def test_does_not_create_client_if_required_settings_missing(self, settings_override, patched_s3_client) -> None:
        with self.settings(**settings_override):
            storage_client = client()
            patched_s3_client.assert_not_called()
            assert storage_client.read_bytes("any_key", 0, 100) is None

    def test_read_bytes_with_byte_range(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"test content"
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        storage.read_bytes("test-key", 5, 10)
        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="test-key", Range="bytes=5-10")

    def test_read_specific_byte_range(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"bcdefghijab"
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        result = storage.read_bytes("test-key", 91, 101)

        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="test-key", Range="bytes=91-101")
        assert result == b"bcdefghijab"
        assert len(result) == 11

    def test_read_returns_none_on_error(self):
        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("error")
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        result = storage.read_bytes("non_existent_file", 0, 100)
        assert result is None
        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="non_existent_file", Range="bytes=0-100")

    def test_fetch_block_success(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        test_data = "test data"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        block_url = f"s3://bucket/key1?range=bytes=0-{len(compressed_data) - 1}"
        result = storage.fetch_block(block_url)

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
    def test_fetch_block_invalid_url(self, invalid_url, expected_error):
        storage = SessionRecordingV2ObjectStorage(MagicMock(), TEST_BUCKET)

        with self.assertRaises(BlockFetchError) as cm:
            storage.fetch_block(invalid_url)
        assert expected_error in str(cm.exception)

    def test_fetch_block_content_not_found(self):
        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=None))}
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        with self.assertRaises(BlockFetchError) as cm:
            storage.fetch_block("s3://bucket/key1?range=bytes=0-100")
        assert "Block content not found" in str(cm.exception)

    def test_fetch_block_wrong_content_length(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"short"  # Only 5 bytes
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        with self.assertRaises(BlockFetchError) as cm:
            storage.fetch_block("s3://bucket/key1?range=bytes=0-100")
        assert "Unexpected data length" in str(cm.exception)

    def test_fetch_block_bytes_success(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        test_data = "test data"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        block_url = f"s3://bucket/key1?range=bytes=0-{len(compressed_data) - 1}"
        result = storage.fetch_block_bytes(block_url)

        assert result == compressed_data
        mock_client.get_object.assert_called_with(
            Bucket=TEST_BUCKET, Key="key1", Range=f"bytes=0-{len(compressed_data) - 1}"
        )

    def test_fetch_block_bytes_returns_compressed_data(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        test_data = "test data for compression"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        block_url = f"s3://bucket/key1?range=bytes=0-{len(compressed_data) - 1}"
        result = storage.fetch_block_bytes(block_url)

        # Verify it returns compressed bytes, not decompressed string
        assert isinstance(result, bytes)
        assert result == compressed_data
        assert result != test_data.encode("utf-8")  # Should NOT be decompressed

    def test_fetch_file_decompresses(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        test_data = "test file content"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        result = storage.fetch_file("test-file-key")

        assert result == test_data
        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="test-file-key")

    def test_fetch_file_bytes_returns_compressed(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        test_data = "test file content"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        result = storage.fetch_file_bytes("test-file-key")

        assert isinstance(result, bytes)
        assert result == compressed_data
        assert result != test_data.encode("utf-8")
        assert snappy.decompress(result).decode("utf-8") == test_data
        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="test-file-key")

    def test_store_lts_recording_success(self):
        mock_client = MagicMock()
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        with override_settings(SESSION_RECORDING_V2_S3_LTS_PREFIX="lts"):
            recording_data = "test recording data"
            target_key, error = storage.store_lts_recording("test_id", recording_data)

            assert error is None
            compressed_data = snappy.compress(recording_data.encode("utf-8"))
            mock_client.put_object.assert_called_with(
                Bucket=TEST_BUCKET,
                Key="lts/test_id",
                Body=compressed_data,
            )
            assert target_key == f"s3://{TEST_BUCKET}/lts/test_id?range=bytes=0-{len(compressed_data) - 1}"

    def test_store_lts_recording_failure(self):
        mock_client = MagicMock()
        mock_client.put_object.side_effect = Exception("Write failed")
        storage = SessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        with override_settings(SESSION_RECORDING_V2_S3_LTS_PREFIX="lts"):
            target_key, error = storage.store_lts_recording("test_id", "test data")

            assert target_key is None
            assert error is not None and "Failed to store LTS recording" in error

    @parameterized.expand(
        [
            ("", False),
            ("lts", True),
        ]
    )
    def test_is_lts_enabled(self, lts_prefix, expected):
        storage = SessionRecordingV2ObjectStorage(MagicMock(), TEST_BUCKET)

        with override_settings(SESSION_RECORDING_V2_S3_LTS_PREFIX=lts_prefix):
            assert storage.is_lts_enabled() is expected


class AsyncContextManager:
    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc, traceback):
        pass


class TestAsyncSessionRecordingV2Storage(APIBaseTest):
    def teardown_method(self, method) -> None:
        pass

    @patch("posthog.storage.session_recording_v2_object_storage.aioboto3")
    async def test_client_constructor_uses_correct_settings(self, patched_aioboto3) -> None:
        # Reset the global client to ensure we test client creation
        import posthog.storage.session_recording_v2_object_storage as storage_module

        client_mock = MagicMock(AsyncContextManager)
        patched_aioboto3.Session.return_value.client = client_mock

        async with storage_module.async_client() as client:
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

            assert isinstance(client, AsyncSessionRecordingV2ObjectStorage)
            assert client.bucket == SESSION_RECORDING_V2_S3_BUCKET

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
    @patch("posthog.storage.session_recording_v2_object_storage.aioboto3")
    async def test_throws_runtimeerror_if_required_settings_missing(self, settings_override, patched_aioboto3) -> None:
        with self.settings(**settings_override):
            client_mock = MagicMock(AsyncContextManager)
            patched_aioboto3.Session.return_value.client = client_mock

            with self.assertRaises(RuntimeError) as _:
                async with async_client() as _:
                    pass

            client_mock.assert_not_called()

    async def test_read_bytes_with_byte_range(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        mock_body.read.return_value = b"test content"
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        await storage.read_bytes("test-key-1", 5, 10)
        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="test-key-1", Range="bytes=5-10")

    async def test_read_specific_byte_range(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        mock_body.read.return_value = b"bcdefghijab"
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        result = await storage.read_bytes("test-key-2", 91, 101)

        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="test-key-2", Range="bytes=91-101")
        assert result == b"bcdefghijab"
        assert len(result) == 11

    async def test_read_returns_none_on_error(self):
        mock_client = AsyncMock()
        mock_client.get_object.side_effect = Exception("error")
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        result = await storage.read_bytes("non_existent_file", 0, 100)
        assert result is None
        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="non_existent_file", Range="bytes=0-100")

    async def test_fetch_block_success(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = "test data"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        block_url = f"s3://bucket/key1?range=bytes=0-{len(compressed_data) - 1}"
        result = await storage.fetch_block(block_url)

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
        storage = AsyncSessionRecordingV2ObjectStorage(AsyncMock(), TEST_BUCKET)

        with self.assertRaises(BlockFetchError) as cm:
            await storage.fetch_block(invalid_url)
        assert expected_error in str(cm.exception)

    async def test_fetch_block_content_not_found(self):
        mock_client = AsyncMock()
        mock_client.get_object.return_value = {"Body": MagicMock(read=AsyncMock(return_value=None))}
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        with self.assertRaises(BlockFetchError) as cm:
            await storage.fetch_block("s3://bucket/key1?range=bytes=0-100")
        assert "Block content not found" in str(cm.exception)

    async def test_fetch_block_wrong_content_length(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        mock_body.read.return_value = b"short"  # Only 5 bytes
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        with self.assertRaises(BlockFetchError) as cm:
            await storage.fetch_block("s3://bucket/key1?range=bytes=0-100")
        assert "Unexpected data length" in str(cm.exception)

    async def test_fetch_block_bytes_success(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = "test data"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        block_url = f"s3://bucket/key1?range=bytes=0-{len(compressed_data) - 1}"
        result = await storage.fetch_block_bytes(block_url)

        assert result == compressed_data
        mock_client.get_object.assert_called_with(
            Bucket=TEST_BUCKET, Key="key1", Range=f"bytes=0-{len(compressed_data) - 1}"
        )

    async def test_fetch_block_bytes_returns_compressed_data(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = "test data for compression"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        block_url = f"s3://bucket/key1?range=bytes=0-{len(compressed_data) - 1}"
        result = await storage.fetch_block_bytes(block_url)

        # Verify it returns compressed bytes, not decompressed string
        assert isinstance(result, bytes)
        assert result == compressed_data
        assert result != test_data.encode("utf-8")  # Should NOT be decompressed

    async def test_fetch_file_decompresses(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = "test file content"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        result = await storage.fetch_file("test-file-key")

        assert result == test_data
        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="test-file-key")

    async def test_fetch_file_bytes_returns_compressed(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = "test file content"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        result = await storage.fetch_file_bytes("test-file-key")

        assert isinstance(result, bytes)
        assert result == compressed_data
        assert result != test_data.encode("utf-8")
        assert snappy.decompress(result).decode("utf-8") == test_data
        mock_client.get_object.assert_called_with(Bucket=TEST_BUCKET, Key="test-file-key")

    async def test_store_lts_recording_success(self):
        mock_client = AsyncMock()
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        with override_settings(SESSION_RECORDING_V2_S3_LTS_PREFIX="lts"):
            recording_data = "test recording data"
            target_key, error = await storage.store_lts_recording("test_id", recording_data)

            assert error is None
            compressed_data = snappy.compress(recording_data.encode("utf-8"))
            mock_client.put_object.assert_called_with(
                Bucket=TEST_BUCKET,
                Key="lts/test_id",
                Body=compressed_data,
            )
            assert target_key == f"s3://{TEST_BUCKET}/lts/test_id?range=bytes=0-{len(compressed_data) - 1}"

    async def test_store_lts_recording_failure(self):
        mock_client = AsyncMock()
        mock_client.put_object.side_effect = Exception("Write failed")
        storage = AsyncSessionRecordingV2ObjectStorage(mock_client, TEST_BUCKET)

        with override_settings(SESSION_RECORDING_V2_S3_LTS_PREFIX="lts"):
            target_key, error = await storage.store_lts_recording("test_id", "test data")

            assert target_key is None
            assert error is not None and "Failed to store LTS recording" in error

    @parameterized.expand(
        [
            ("", False),
            ("lts", True),
        ]
    )
    def test_is_lts_enabled(self, lts_prefix, expected):
        storage = AsyncSessionRecordingV2ObjectStorage(AsyncMock(), TEST_BUCKET)

        with override_settings(SESSION_RECORDING_V2_S3_LTS_PREFIX=lts_prefix):
            assert storage.is_lts_enabled() is expected
