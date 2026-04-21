import os
import re
import shutil
import tempfile

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from boto3 import resource
from botocore.config import Config
from rest_framework import status

from posthog.models import UploadedMedia
from posthog.models.utils import UUIDT
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

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
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media",
                    {"image": image},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
                assert response.json()["name"] == "a-small-but-valid.gif"
                media_location = response.json()["image_location"]
                assert re.match(r"^http://localhost:8010/uploaded_media/.*", media_location) is not None

            self.client.logout()
            response = self.client.get(media_location)

            assert response.status_code == status.HTTP_200_OK
            assert response.headers["Content-Type"] == "image/gif"

    def test_missing_token_from_different_origin_returns_401(self) -> None:
        self.client.logout()

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media/",
                    {"image": image},
                    format="multipart",
                    headers={"Origin": "https://somewebsite.com"},
                )
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.json())

    def test_rejects_non_image_file_type(self) -> None:
        fake_file = SimpleUploadedFile(name="test_image.jpg", content=b"a fake image", content_type="text/csv")
        response = self.client.post(
            f"/api/projects/{self.team.id}/uploaded_media",
            {"image": fake_file},
            format="multipart",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            response.json(),
        )

    def test_rejects_file_manually_crafted_to_start_with_image_magic_bytes(self) -> None:
        with open(get_path_to("file-masquerading-as-a.gif"), "rb") as image:
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media",
                {"image": image},
                format="multipart",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

            assert UploadedMedia.objects.count() == 0

    def test_made_up_id_is_404(self) -> None:
        response = self.client.get(f"/uploaded_media/{UUIDT()}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_rejects_too_large_file_type(self) -> None:
        four_megabytes_plus_a_little = b"1" * (4 * 1024 * 1024 + 1)
        fake_big_file = SimpleUploadedFile(
            name="test_image.jpg",
            content=four_megabytes_plus_a_little,
            content_type="image/jpeg",
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/uploaded_media",
            {"image": fake_big_file},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertEqual(response.json()["detail"], "Uploaded media must be less than 4MB")

    def test_download_sets_nosniff_and_strict_csp(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media",
                    {"image": image},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
                media_location = response.json()["image_location"]

            self.client.logout()
            download_response = self.client.get(media_location)

            assert download_response.status_code == status.HTTP_200_OK
            assert download_response.headers.get("X-Content-Type-Options") == "nosniff"
            # CSPMiddleware applies default-src 'none' on non-HTML responses.
            csp = download_response.headers.get("Content-Security-Policy", "")
            assert "default-src 'none'" in csp

    def test_download_forces_attachment_for_non_image_content_type(self) -> None:
        # Simulate a stored row with an attacker-controlled content type (bypassing
        # any upload-time validation) to verify the download endpoint does not
        # render the content inline.
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media",
                    {"image": image},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
                media_id = response.json()["id"]

            media = UploadedMedia.objects.get(id=media_id)
            media.content_type = "text/html"
            media.save(update_fields=["content_type"])

            self.client.logout()
            with patch(
                "posthog.api.uploaded_media.object_storage.read_bytes",
                return_value=b"<script>alert(1)</script>",
            ):
                download_response = self.client.get(f"/uploaded_media/{media_id}")

            assert download_response.status_code == status.HTTP_200_OK
            assert download_response.headers.get("Content-Type", "").startswith("application/octet-stream")
            disposition = download_response.headers.get("Content-Disposition", "")
            assert disposition.startswith("attachment")

    def test_download_serves_safe_images_inline(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media",
                    {"image": image},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
                media_location = response.json()["image_location"]

            self.client.logout()
            download_response = self.client.get(media_location)

            assert download_response.status_code == status.HTTP_200_OK
            assert download_response.headers["Content-Type"] == "image/gif"
            # Safe raster images may render inline (no Content-Disposition: attachment)
            assert "attachment" not in download_response.headers.get("Content-Disposition", "")

    def test_rejects_upload_when_object_storage_is_unavailable(self) -> None:
        with override_settings(OBJECT_STORAGE_ENABLED=False):
            fake_big_file = SimpleUploadedFile(name="test_image.jpg", content=b"", content_type="image/jpeg")
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media",
                {"image": fake_big_file},
                format="multipart",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
            self.assertEqual(
                response.json()["detail"],
                "Object storage must be available to allow media uploads.",
            )
