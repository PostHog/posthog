import uuid
from unittest.mock import patch

from boto3 import resource
from botocore.client import Config

from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage.object_storage import health_check, list_matching_objects, read, write
from posthog.test.base import APIBaseTest

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
            self.assertFalse(health_check())
            patched_s3_client.assert_not_called()

    def test_write_and_read_works_with_known_content(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            session_id = str(uuid.uuid4())
            chunk_id = uuid.uuid4()
            name = f"{session_id}/{0}-{chunk_id}"
            file_name = f"{TEST_BUCKET}/test_write_and_read_works_with_known_content/{name}"
            write(file_name, "my content")
            self.assertEqual(read(file_name), "my content")

    def test_listing_objects(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            prefix = f"{TEST_BUCKET}/test_listing_objects"
            file_one = f"{prefix}/one"
            file_two = f"{prefix}/two"
            write(file_one, "my content")
            write(file_two, "my content")
            self.assertEqual(list_matching_objects(prefix), [file_one, file_two])
