import re
import uuid
import socket

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from boto3 import resource
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from parameterized import parameterized
from urllib3.exceptions import NewConnectionError

from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage.object_storage import (
    ObjectStorage,
    ObjectStorageError,
    copy_objects,
    get_presigned_post,
    get_presigned_url,
    health_check,
    is_transient_connection_error,
    list_objects,
    read,
    write,
)

TEST_BUCKET = "test_storage_bucket"


class TestStorage(APIBaseTest):
    def teardown_method(self, method) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

    @patch("posthog.storage.object_storage.client")
    def test_does_not_create_client_if_storage_is_disabled(self, patched_s3_client) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            assert not health_check()
            patched_s3_client.assert_not_called()

    def test_write_and_read_works_with_known_content(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            session_id = str(uuid.uuid4())
            chunk_id = uuid.uuid4()
            name = f"{session_id}/{0}-{chunk_id}"
            file_name = f"{TEST_BUCKET}/test_write_and_read_works_with_known_content/{name}"
            write(file_name, "my content")
            assert read(file_name) == "my content"

    def test_write_and_read_works_with_known_byte_content(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            session_id = str(uuid.uuid4())
            chunk_id = uuid.uuid4()
            name = f"{session_id}/{0}-{chunk_id}"
            file_name = f"{TEST_BUCKET}/test_write_and_read_works_with_known_content/{name}"
            write(file_name, b"my content")
            assert read(file_name) == "my content"

    def test_can_generate_presigned_url_for_existing_file(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            session_id = str(uuid.uuid4())
            chunk_id = uuid.uuid4()
            name = f"{session_id}/{0}-{chunk_id}"
            file_name = f"{TEST_BUCKET}/test_can_generate_presigned_url_for_existing_file/{name}"
            write(file_name, b"my content")

            presigned_url = get_presigned_url(file_name)
            assert presigned_url is not None
            assert re.match(
                r"^http://localhost:\d+/posthog/test_storage_bucket/test_can_generate_presigned_url_for_existing_file/.*\?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=.*$",
                presigned_url,
            )

    def test_can_generate_presigned_url_for_non_existent_file(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            name = "a/b-c"
            file_name = f"{TEST_BUCKET}/test_can_ignore_presigned_url_for_non_existent_file/{name}"

            presigned_url = get_presigned_url(file_name)
            assert presigned_url is not None
            assert re.match(
                r"^http://localhost:\d+/posthog/test_storage_bucket/test_can_ignore_presigned_url_for_non_existent_file/.*?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=.*$",
                presigned_url,
            )

    def test_can_generate_presigned_post_url(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            file_name = f"{TEST_BUCKET}/test_can_generate_presigned_upload_url/{uuid.uuid4()}"

            presigned_url = get_presigned_post(file_name, conditions=[])
            assert presigned_url is not None
            assert "fields" in presigned_url
            assert re.match(
                r"^http://localhost:\d+/posthog",
                presigned_url["url"],
            )

    def test_can_list_objects_with_prefix(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            shared_prefix = "a_shared_prefix"

            for file in ["a", "b", "c"]:
                file_name = f"{TEST_BUCKET}/{shared_prefix}/{file}"
                write(file_name, b"my content")

            listing = list_objects(prefix=f"{TEST_BUCKET}/{shared_prefix}")

            assert listing == [
                "test_storage_bucket/a_shared_prefix/a",
                "test_storage_bucket/a_shared_prefix/b",
                "test_storage_bucket/a_shared_prefix/c",
            ]

    def test_can_list_unknown_prefix(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            shared_prefix = str(uuid.uuid4())

            listing = list_objects(prefix=shared_prefix)

            assert listing is None

    def test_can_copy_objects_between_prefixes(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            shared_prefix = "a_shared_prefix"

            for file in ["a", "b", "c"]:
                file_name = f"{TEST_BUCKET}/{shared_prefix}/{file}"
                write(file_name, b"my content")

            copied_count = copy_objects(
                source_prefix=f"{TEST_BUCKET}/{shared_prefix}",
                target_prefix=f"{TEST_BUCKET}/the_destination/folder",
            )
            assert copied_count == 3

            listing = list_objects(prefix=f"{TEST_BUCKET}")

            assert listing == [
                "test_storage_bucket/a_shared_prefix/a",
                "test_storage_bucket/a_shared_prefix/b",
                "test_storage_bucket/a_shared_prefix/c",
                "test_storage_bucket/the_destination/folder/a",
                "test_storage_bucket/the_destination/folder/b",
                "test_storage_bucket/the_destination/folder/c",
            ]

    def test_can_safely_copy_objects_from_unknown_prefix(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            shared_prefix = "a_shared_prefix"

            for file in ["a", "b", "c"]:
                file_name = f"{TEST_BUCKET}/{shared_prefix}/{file}"
                write(file_name, b"my content")

            copied_count = copy_objects(
                source_prefix=f"nothing_here",
                target_prefix=f"{TEST_BUCKET}/the_destination/folder",
            )
            assert copied_count == 0

            listing = list_objects(prefix=f"{TEST_BUCKET}")

            assert listing == [
                "test_storage_bucket/a_shared_prefix/a",
                "test_storage_bucket/a_shared_prefix/b",
                "test_storage_bucket/a_shared_prefix/c",
            ]

    def test_read_bytes(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"test content"
        mock_client.get_object.return_value = {"Body": mock_body}
        storage = ObjectStorage(mock_client)

        result = storage.read_bytes("test-bucket", "test-key")
        mock_client.get_object.assert_called_with(Bucket="test-bucket", Key="test-key")
        assert result == b"test content"

    def test_read_bytes_returns_none_for_nosuchkey_when_missing_ok(self):
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}}
        mock_client.get_object.side_effect = ClientError(error_response, "GetObject")  # type: ignore[arg-type]
        storage = ObjectStorage(mock_client)

        result = storage.read_bytes("test-bucket", "nonexistent-key", missing_ok=True)
        assert result is None

    def test_read_bytes_raises_for_nosuchkey_by_default(self):
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}}
        mock_client.get_object.side_effect = ClientError(error_response, "GetObject")  # type: ignore[arg-type]
        storage = ObjectStorage(mock_client)

        with self.assertRaises(ObjectStorageError):
            storage.read_bytes("test-bucket", "nonexistent-key")

    def test_read_bytes_raises_for_other_client_errors(self):
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}
        mock_client.get_object.side_effect = ClientError(error_response, "GetObject")  # type: ignore[arg-type]
        storage = ObjectStorage(mock_client)

        with self.assertRaises(ObjectStorageError):
            storage.read_bytes("test-bucket", "test-key")

    @parameterized.expand(
        [
            ("gaierror", socket.gaierror(-2, "Name or service not known"), True),
            ("endpoint_connection", EndpointConnectionError(endpoint_url="http://objectstorage:19000"), True),
            ("builtin_connection_reset", ConnectionResetError("Connection reset by peer"), True),
            (
                "urllib3_new_connection",
                NewConnectionError(None, "Failed to establish a new connection"),
                True,
            ),
            ("value_error", ValueError("something else"), False),
            ("client_error", ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject"), False),
        ]
    )
    def test_is_transient_connection_error(self, _name, error, expected):
        assert is_transient_connection_error(error) is expected

    def test_is_transient_connection_error_walks_cause_chain(self):
        wrapped = ObjectStorageError("read failed")
        wrapped.__cause__ = socket.gaierror(-2, "Name or service not known")
        assert is_transient_connection_error(wrapped) is True

    def test_read_bytes_skips_capture_for_transient_connection_error(self):
        mock_client = MagicMock()
        mock_client.get_object.side_effect = EndpointConnectionError(endpoint_url="http://objectstorage:19000")
        storage = ObjectStorage(mock_client)

        with patch("posthog.storage.object_storage.capture_exception") as mock_capture:
            with self.assertRaises(ObjectStorageError):
                storage.read_bytes("test-bucket", "test-key")
            mock_capture.assert_not_called()

    def test_read_bytes_captures_genuine_client_error(self):
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}
        mock_client.get_object.side_effect = ClientError(error_response, "GetObject")  # type: ignore[arg-type]
        storage = ObjectStorage(mock_client)

        with patch("posthog.storage.object_storage.capture_exception") as mock_capture:
            with self.assertRaises(ObjectStorageError):
                storage.read_bytes("test-bucket", "test-key")
            mock_capture.assert_called_once()

    def test_write_skips_capture_for_transient_connection_error(self):
        mock_client = MagicMock()
        mock_client.put_object.side_effect = socket.gaierror(-2, "Name or service not known")
        storage = ObjectStorage(mock_client)

        with patch("posthog.storage.object_storage.capture_exception") as mock_capture:
            with self.assertRaises(ObjectStorageError):
                storage.write("test-bucket", "test-key", b"content", None)
            mock_capture.assert_not_called()

    def test_write_captures_genuine_error(self):
        mock_client = MagicMock()
        mock_client.put_object.side_effect = ValueError("not a connection problem")
        storage = ObjectStorage(mock_client)

        with patch("posthog.storage.object_storage.capture_exception") as mock_capture:
            with self.assertRaises(ObjectStorageError):
                storage.write("test-bucket", "test-key", b"content", None)
            mock_capture.assert_called_once()
