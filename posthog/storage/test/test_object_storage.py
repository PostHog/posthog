import re
import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from boto3 import resource
from botocore.client import Config

from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage.object_storage import (
    ObjectStorage,
    copy_objects,
    get_presigned_post,
    get_presigned_url,
    health_check,
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
