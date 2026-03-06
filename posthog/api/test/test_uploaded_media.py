import os
import re
import shutil
import tempfile

from posthog.test.base import APIBaseTest

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from boto3 import resource
from botocore.config import Config
from parameterized import parameterized
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

    def test_soft_deleted_media_returns_404(self) -> None:
        media = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name="test.gif",
            content_type="image/gif",
        )
        media.deleted = True
        media.save()

        response = self.client.get(f"/uploaded_media/{media.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestExtractMediaUuids(TestCase):
    @parameterized.expand(
        [
            ("empty string", "", set()),
            ("no uuids", "hello world", set()),
            (
                "single uuid",
                'text with <img src="/uploaded_media/01234567-89ab-cdef-0123-456789abcdef"/>',
                {"01234567-89ab-cdef-0123-456789abcdef"},
            ),
            (
                "multiple uuids",
                "/uploaded_media/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee and /uploaded_media/11111111-2222-3333-4444-555555555555",
                {"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "11111111-2222-3333-4444-555555555555"},
            ),
            (
                "duplicate uuids deduplicated",
                "/uploaded_media/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee /uploaded_media/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                {"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
            ),
        ]
    )
    def test_extract_media_uuids(self, _name: str, text_body: str, expected: set[str]) -> None:
        assert UploadedMedia.extract_media_uuids(text_body) == expected


class TestSoftDeleteForRemovedImages(APIBaseTest):
    def test_soft_deletes_removed_images(self) -> None:
        media = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name="test.gif",
            content_type="image/gif",
        )
        old_body = f'<img src="/uploaded_media/{media.id}"/>'
        UploadedMedia.soft_delete_for_removed_images(old_body, "no images here", self.team.id)

        media.refresh_from_db()
        assert media.deleted is True

    def test_keeps_images_still_referenced(self) -> None:
        media = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name="test.gif",
            content_type="image/gif",
        )
        body = f'<img src="/uploaded_media/{media.id}"/>'
        UploadedMedia.soft_delete_for_removed_images(body, body, self.team.id)

        media.refresh_from_db()
        assert media.deleted is False

    def test_delete_all_when_new_body_is_none(self) -> None:
        media = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name="test.gif",
            content_type="image/gif",
        )
        old_body = f'<img src="/uploaded_media/{media.id}"/>'
        UploadedMedia.soft_delete_for_removed_images(old_body, None, self.team.id)

        media.refresh_from_db()
        assert media.deleted is True

    def test_does_not_affect_other_teams(self) -> None:
        media = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name="test.gif",
            content_type="image/gif",
        )
        old_body = f'<img src="/uploaded_media/{media.id}"/>'
        UploadedMedia.soft_delete_for_removed_images(old_body, None, self.team.id + 999)

        media.refresh_from_db()
        assert media.deleted is False


class TestRestoreForTextBodies(APIBaseTest):
    def test_restores_deleted_media_referenced_in_bodies(self) -> None:
        media = UploadedMedia.objects.create(
            team=self.team, created_by=self.user, file_name="t.gif", content_type="image/gif", deleted=True
        )
        body = f'<img src="/uploaded_media/{media.id}"/>'
        UploadedMedia.restore_for_text_bodies([body], self.team.id)

        media.refresh_from_db()
        assert media.deleted is False

    def test_does_not_affect_other_teams(self) -> None:
        media = UploadedMedia.objects.create(
            team=self.team, created_by=self.user, file_name="t.gif", content_type="image/gif", deleted=True
        )
        body = f'<img src="/uploaded_media/{media.id}"/>'
        UploadedMedia.restore_for_text_bodies([body], self.team.id + 999)

        media.refresh_from_db()
        assert media.deleted is True

    def test_noop_on_empty_bodies(self) -> None:
        media = UploadedMedia.objects.create(
            team=self.team, created_by=self.user, file_name="t.gif", content_type="image/gif", deleted=True
        )
        UploadedMedia.restore_for_text_bodies([], self.team.id)

        media.refresh_from_db()
        assert media.deleted is True
