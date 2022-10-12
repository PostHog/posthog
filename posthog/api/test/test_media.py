import os
import re
import shutil
import tempfile

from boto3 import resource
from botocore.config import Config
from django.test import override_settings
from rest_framework import status

from posthog.models import UploadedMedia
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage import object_storage
from posthog.test.base import APIBaseTest

MEDIA_ROOT = tempfile.mkdtemp()

TEST_BUCKET = "Test-Uploads"


def get_path_to(fixture_file: str) -> str:
    file_dir = os.path.dirname(__file__)
    return os.path.join(file_dir, "fixtures", fixture_file)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class TestMediaAPI(APIBaseTest):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)  # delete the temp dir
        # delete s3 files
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

        super().tearDownClass()

    def test_can_upload_and_retrieve_a_file(self) -> None:
        file_name = "small-dancing-banana.gif"
        with open(get_path_to(file_name), "rb") as to_upload:
            with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
                response = self.client.post(
                    f"/api/projects/{self.team.id}/media", {"image": to_upload}, format="multipart"
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
                assert response.json()["name"] == file_name
                media_location = response.json()["image_location"]
                assert re.match(r"^http://localhost:8000/media/.*", media_location) is not None

                upload = UploadedMedia.objects.get(id=response.json()["id"])

                content = object_storage.read_bytes(upload.media_location)
                assert content is not None

                self.client.logout()
                response = self.client.get(media_location)

                assert response.status_code == status.HTTP_200_OK
                assert response.headers["Content-Type"] == "image/gif"

    def test_rejects_non_image_file_type(self) -> None:
        with open(get_path_to("example.csv"), "rb") as to_upload:
            response = self.client.post(f"/api/projects/{self.team.id}/media", {"image": to_upload}, format="multipart")
            self.assertEqual(response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, response.json())
