import os
import re
import shutil
import tempfile

from boto3 import resource
from botocore.config import Config
from django.core.files.uploadedfile import SimpleUploadedFile
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
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            fake_file = SimpleUploadedFile(name="test_image.jpg", content=b"a fake image", content_type="image/jpeg")
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media", {"image": fake_file}, format="multipart"
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
            assert response.json()["name"] == "test_image.jpg"
            media_location = response.json()["image_location"]
            assert re.match(r"^http://localhost:8000/uploaded_media/.*/test_image.jpg", media_location) is not None

            upload = UploadedMedia.objects.get(id=response.json()["id"])

            content = object_storage.read_bytes(upload.media_location)
            assert content == b"a fake image"

            self.client.logout()
            response = self.client.get(media_location)

            assert response.status_code == status.HTTP_200_OK
            assert response.headers["Content-Type"] == "image/jpeg"

    def test_url_encodes_filename_before_use(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            maybe_dangerous_filename = "the|user provided#file%name+.jpg?redirect-hackers.io"
            fake_file = SimpleUploadedFile(
                name=maybe_dangerous_filename, content=b"a fake image", content_type="image/jpeg"
            )
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media", {"image": fake_file}, format="multipart"
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
            assert response.json()["name"] == maybe_dangerous_filename
            media_location = response.json()["image_location"]
            assert media_location.endswith("the%7Cuser%20provided%23file%25name%2B.jpg%3Fredirect-hackers.io")

            # url encoded filenames can still be loaded
            self.client.logout()
            response = self.client.get(media_location)

            assert response.status_code == status.HTTP_200_OK
            assert response.headers["Content-Type"] == "image/jpeg"

    def test_rejects_non_image_file_type(self) -> None:
        fake_file = SimpleUploadedFile(name="test_image.jpg", content=b"a fake image", content_type="text/csv")
        response = self.client.post(
            f"/api/projects/{self.team.id}/uploaded_media", {"image": fake_file}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, response.json())

    def test_rejects_too_large_file_type(self) -> None:
        four_megabytes_plus_a_little = b"1" * (4 * 1024 * 1024 + 1)
        fake_big_file = SimpleUploadedFile(
            name="test_image.jpg", content=four_megabytes_plus_a_little, content_type="image/jpeg"
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/uploaded_media", {"image": fake_big_file}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertEqual(response.json()["detail"], "Uploaded media must be less than 4MB")

    def test_rejects_upload_when_object_storage_is_unavailable(self) -> None:
        with override_settings(OBJECT_STORAGE_ENABLED=False):
            fake_big_file = SimpleUploadedFile(name="test_image.jpg", content=b"", content_type="image/jpeg")
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media", {"image": fake_big_file}, format="multipart"
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
            self.assertEqual(response.json()["detail"], "Object storage must be available to allow media uploads.")
