import unittest
import uuid

from boto3 import resource
from botocore.client import Config

from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage.object_storage import read, write

TEST_BUCKET = "test_storage_bucket"


class TestStorage(unittest.TestCase):
    def teardown_method(self, method):
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

    def test_write_and_read_works_with_known_content(self):
        session_id = str(uuid.uuid4())
        chunk_id = uuid.uuid4()
        name = f"{session_id}/{0}-{chunk_id}"
        file_name = f"{TEST_BUCKET}/test_write_and_read_works_with_known_content/{name}"
        write(file_name, "my content")
        self.assertEqual(read(file_name), "my content")
