import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

import snappy
from parameterized import parameterized

from posthog.storage.recordings.errors import FileFetchError, FileUploadError
from posthog.storage.recordings.file_storage import AsyncFileStorage, FileStorage, async_file_storage, file_storage

TEST_BUCKET = "test_file_bucket"


class AsyncContextManager:
    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc, traceback):
        pass


class TestFileStorage(APIBaseTest):
    def teardown_method(self, method) -> None:
        pass

    @patch("posthog.storage.recordings.file_storage.boto3_client")
    def test_client_uses_correct_settings(self, patched_boto3_client) -> None:
        from posthog.settings.session_replay_v2 import (
            SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
            SESSION_RECORDING_V2_S3_BUCKET,
            SESSION_RECORDING_V2_S3_ENDPOINT,
            SESSION_RECORDING_V2_S3_REGION,
            SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
        )

        storage = file_storage()

        assert patched_boto3_client.call_count == 1
        call_args = patched_boto3_client.call_args[0]
        call_kwargs = patched_boto3_client.call_args[1]

        assert call_args == ("s3",)
        assert call_kwargs["endpoint_url"] == SESSION_RECORDING_V2_S3_ENDPOINT
        assert call_kwargs["aws_access_key_id"] == SESSION_RECORDING_V2_S3_ACCESS_KEY_ID
        assert call_kwargs["aws_secret_access_key"] == SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY
        assert call_kwargs["region_name"] == SESSION_RECORDING_V2_S3_REGION

        assert isinstance(storage, FileStorage)
        assert storage._bucket == SESSION_RECORDING_V2_S3_BUCKET

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
    @patch("posthog.storage.recordings.file_storage.boto3_client")
    def test_client_raises_error_if_required_settings_missing(self, settings_override, patched_boto3_client) -> None:
        with self.settings(**settings_override):
            with pytest.raises(RuntimeError, match="Missing required settings"):
                file_storage()
            patched_boto3_client.assert_not_called()

    def test_upload_file_success(self):
        mock_client = MagicMock()
        storage = FileStorage(mock_client, TEST_BUCKET)

        storage.upload_file("test/key", "/path/to/file.zip")

        mock_client.upload_file.assert_called_once_with(
            Filename="/path/to/file.zip",
            Bucket=TEST_BUCKET,
            Key="test/key",
        )

    def test_upload_file_error_raises_exception(self):
        mock_client = MagicMock()
        mock_client.upload_file.side_effect = Exception("S3 error")
        storage = FileStorage(mock_client, TEST_BUCKET)

        with pytest.raises(FileUploadError, match="Failed to upload file"):
            storage.upload_file("test/key", "/path/to/file.zip")

    def test_download_file_success(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        test_data = b"file content"
        mock_body.read.return_value = test_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = FileStorage(mock_client, TEST_BUCKET)

        result = storage.download_file("test/key")

        assert result == test_data
        mock_client.get_object.assert_called_once_with(Bucket=TEST_BUCKET, Key="test/key")

    def test_download_file_error_raises_exception(self):
        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("S3 error")
        storage = FileStorage(mock_client, TEST_BUCKET)

        with pytest.raises(FileFetchError, match="Failed to download file"):
            storage.download_file("test/key")

    def test_download_file_decompressed_success(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        test_data = "decompressed content"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read.return_value = compressed_data
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = FileStorage(mock_client, TEST_BUCKET)

        result = storage.download_file_decompressed("test/key")

        assert result == test_data

    def test_download_file_decompressed_invalid_snappy_raises_exception(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"not valid snappy data"
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = FileStorage(mock_client, TEST_BUCKET)

        with pytest.raises(FileFetchError, match="Failed to decompress file"):
            storage.download_file_decompressed("test/key")

    def test_download_file_decompressed_propagates_fetch_error(self):
        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("S3 error")
        storage = FileStorage(mock_client, TEST_BUCKET)

        with pytest.raises(FileFetchError, match="Failed to download file"):
            storage.download_file_decompressed("test/key")


class TestAsyncFileStorage(APIBaseTest):
    def teardown_method(self, method) -> None:
        pass

    @patch("posthog.storage.recordings.file_storage.aioboto3")
    async def test_async_client_uses_correct_settings(self, patched_aioboto3) -> None:
        from posthog.settings.session_replay_v2 import (
            SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
            SESSION_RECORDING_V2_S3_BUCKET,
            SESSION_RECORDING_V2_S3_ENDPOINT,
            SESSION_RECORDING_V2_S3_REGION,
            SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
        )

        client_mock = MagicMock(AsyncContextManager)
        patched_aioboto3.Session.return_value.client = client_mock

        async with async_file_storage() as storage:
            assert patched_aioboto3.Session.call_count == 1
            assert client_mock.call_count == 1

            call_args = client_mock.call_args[0]
            call_kwargs = client_mock.call_args[1]

            assert call_args == ("s3",)
            assert call_kwargs["endpoint_url"] == SESSION_RECORDING_V2_S3_ENDPOINT
            assert call_kwargs["aws_access_key_id"] == SESSION_RECORDING_V2_S3_ACCESS_KEY_ID
            assert call_kwargs["aws_secret_access_key"] == SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY
            assert call_kwargs["region_name"] == SESSION_RECORDING_V2_S3_REGION

            assert isinstance(storage, AsyncFileStorage)
            assert storage._bucket == SESSION_RECORDING_V2_S3_BUCKET

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
    async def test_async_client_raises_error_if_required_settings_missing(self, settings_override) -> None:
        with self.settings(**settings_override):
            with pytest.raises(RuntimeError, match="Missing required settings"):
                async with async_file_storage():
                    pass

    async def test_upload_file_success(self):
        mock_client = AsyncMock()
        storage = AsyncFileStorage(mock_client, TEST_BUCKET)

        await storage.upload_file("test/key", "/path/to/file.zip")

        mock_client.upload_file.assert_called_once_with(
            Filename="/path/to/file.zip",
            Bucket=TEST_BUCKET,
            Key="test/key",
        )

    async def test_upload_file_error_raises_exception(self):
        mock_client = AsyncMock()
        mock_client.upload_file.side_effect = Exception("S3 error")
        storage = AsyncFileStorage(mock_client, TEST_BUCKET)

        with pytest.raises(FileUploadError, match="Failed to upload file"):
            await storage.upload_file("test/key", "/path/to/file.zip")

    async def test_download_file_success(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = b"file content"
        mock_body.read = AsyncMock(return_value=test_data)
        mock_client.get_object = AsyncMock(return_value={"Body": mock_body})
        storage = AsyncFileStorage(mock_client, TEST_BUCKET)

        result = await storage.download_file("test/key")

        assert result == test_data
        mock_client.get_object.assert_called_once_with(Bucket=TEST_BUCKET, Key="test/key")

    async def test_download_file_error_raises_exception(self):
        mock_client = AsyncMock()
        mock_client.get_object.side_effect = Exception("S3 error")
        storage = AsyncFileStorage(mock_client, TEST_BUCKET)

        with pytest.raises(FileFetchError, match="Failed to download file"):
            await storage.download_file("test/key")

    async def test_download_file_decompressed_success(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        test_data = "decompressed content"
        compressed_data = snappy.compress(test_data.encode("utf-8"))
        mock_body.read = AsyncMock(return_value=compressed_data)
        mock_client.get_object = AsyncMock(return_value={"Body": mock_body})
        storage = AsyncFileStorage(mock_client, TEST_BUCKET)

        result = await storage.download_file_decompressed("test/key")

        assert result == test_data

    async def test_download_file_decompressed_invalid_snappy_raises_exception(self):
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        mock_body.read = AsyncMock(return_value=b"not valid snappy data")
        mock_client.get_object = AsyncMock(return_value={"Body": mock_body})
        storage = AsyncFileStorage(mock_client, TEST_BUCKET)

        with pytest.raises(FileFetchError, match="Failed to decompress file"):
            await storage.download_file_decompressed("test/key")

    async def test_download_file_decompressed_propagates_fetch_error(self):
        mock_client = AsyncMock()
        mock_client.get_object = AsyncMock(side_effect=Exception("S3 error"))
        storage = AsyncFileStorage(mock_client, TEST_BUCKET)

        with pytest.raises(FileFetchError, match="Failed to download file"):
            await storage.download_file_decompressed("test/key")
