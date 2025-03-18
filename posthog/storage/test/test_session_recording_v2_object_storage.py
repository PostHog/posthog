from unittest.mock import patch, MagicMock

from botocore.client import Config

from posthog.settings.session_replay_v2 import (
    SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
    SESSION_RECORDING_V2_S3_BUCKET,
    SESSION_RECORDING_V2_S3_ENDPOINT,
    SESSION_RECORDING_V2_S3_REGION,
    SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
)
from posthog.storage.session_recording_v2_object_storage import (
    client,
    SessionRecordingV2ObjectStorage,
)
from posthog.test.base import APIBaseTest

TEST_BUCKET = "test_session_recording_v2_bucket"


class TestSessionRecordingV2Storage(APIBaseTest):
    def teardown_method(self, method) -> None:
        pass

    @patch("posthog.storage.session_recording_v2_object_storage.boto3_client")
    def test_client_constructor_uses_correct_settings(self, patched_boto3_client) -> None:
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
        assert config.signature_version == "s3v4"
        assert config.connect_timeout == 1
        assert config.retries == {"max_attempts": 1}

        # Check the returned client
        assert isinstance(storage_client, SessionRecordingV2ObjectStorage)
        assert storage_client.bucket == SESSION_RECORDING_V2_S3_BUCKET

    @patch("posthog.storage.session_recording_v2_object_storage.boto3_client")
    def test_does_not_create_client_if_required_settings_missing(self, patched_s3_client) -> None:
        test_cases = [
            {"SESSION_RECORDING_V2_S3_BUCKET": ""},
            {"SESSION_RECORDING_V2_S3_ENDPOINT": ""},
            {"SESSION_RECORDING_V2_S3_REGION": ""},
            {
                "SESSION_RECORDING_V2_S3_BUCKET": "",
                "SESSION_RECORDING_V2_S3_ENDPOINT": "",
                "SESSION_RECORDING_V2_S3_REGION": "",
            },
        ]

        for settings_override in test_cases:
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
