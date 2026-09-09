import io
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
from parameterized import parameterized
from PIL import Image
from rest_framework import status

from posthog.api.uploaded_media import FOUR_MEGABYTES
from posthog.models import Team, UploadedMedia
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import UUIDT, generate_random_token_personal
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

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

    @parameterized.expand(
        [
            ("bmp", "BMP", "image/bmp"),
            ("avif", "AVIF", "image/avif"),
        ]
    )
    def test_accepts_every_format_the_download_route_treats_as_inline_safe(
        self, _name: str, pillow_format: str, expected_content_type: str
    ) -> None:
        # Any format download() serves inline must also be accepted on upload, or the sniffer
        # silently narrows what text cards, notebooks and org logos can store. Encoding is not
        # guarded: a Pillow build that drops one of these formats is itself the regression,
        # because download() would still promise to serve it.
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), color="red").save(buffer, format=pillow_format)
        fake_file = SimpleUploadedFile(
            name=f"logo.{_name}", content=buffer.getvalue(), content_type=expected_content_type
        )
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media",
                {"image": fake_file},
                format="multipart",
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

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

    @parameterized.expand(
        [
            ("png", "image/png", True),
            ("jpeg", "image/jpeg", True),
            ("gif", "image/gif", True),
            ("webp", "image/webp", True),
            ("avif", "image/avif", True),
            ("bmp", "image/bmp", True),
            ("html", "text/html", False),
            ("svg", "image/svg+xml", False),
            ("javascript", "application/javascript", False),
            ("xml", "application/xml", False),
            ("octet_stream", "application/octet-stream", False),
        ]
    )
    def test_download_inline_vs_attachment(self, _name: str, content_type: str, inline: bool) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media",
                    {"image": image},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
                media_id = response.json()["id"]

            UploadedMedia.objects.filter(id=media_id).update(content_type=content_type)

            self.client.logout()
            with patch(
                "posthog.api.uploaded_media.object_storage.read_bytes",
                return_value=b"bytes",
            ):
                download_response = self.client.get(f"/uploaded_media/{media_id}")

        assert download_response.status_code == status.HTTP_200_OK
        if inline:
            assert download_response.headers["Content-Type"] == content_type
            assert "attachment" not in download_response.headers.get("Content-Disposition", "")
        else:
            assert download_response.headers["Content-Type"].startswith("application/octet-stream")
            assert download_response.headers.get("Content-Disposition", "").startswith("attachment")

    @parameterized.expand(
        [
            ("plain", "example.docx", 'attachment; filename="example.docx"'),
            ("quotes", 'a"b.docx', 'attachment; filename="a\\"b.docx"'),
            ("crlf_injection", "evil.docx\r\nSet-Cookie: x=1", 'attachment; filename="evil.docxSet-Cookie: x=1"'),
            ("unicode", "réport.docx", "attachment; filename=\"rport.docx\"; filename*=UTF-8''r%C3%A9port.docx"),
        ]
    )
    def test_download_preserves_filename(self, _name: str, file_name: str, expected_disposition: str) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media",
                    {"image": image},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
                media_id = response.json()["id"]

            UploadedMedia.objects.filter(id=media_id).update(
                content_type="application/octet-stream", file_name=file_name
            )

            self.client.logout()
            with patch(
                "posthog.api.uploaded_media.object_storage.read_bytes",
                return_value=b"bytes",
            ):
                download_response = self.client.get(f"/uploaded_media/{media_id}")

        assert download_response.status_code == status.HTTP_200_OK
        assert download_response.headers["Content-Disposition"] == expected_disposition

    def test_download_returns_404_when_object_storage_key_is_missing(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media",
                    {"image": image},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
                media_id = response.json()["id"]

            self.client.logout()
            with patch(
                "posthog.api.uploaded_media.object_storage.read_bytes",
                return_value=None,
            ):
                download_response = self.client.get(f"/uploaded_media/{media_id}")

        assert download_response.status_code == status.HTTP_404_NOT_FOUND

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


class TestMediaLibraryAPI(APIBaseTest):
    """The media library surface: purpose-scoped listing and the presigned upload flow."""

    def _create_media(self, purpose: str | None = None, file_name: str = "logo.png", **kwargs) -> UploadedMedia:
        return UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name=file_name,
            content_type="image/png",
            media_location=f"{TEST_BUCKET}/team-{self.team.pk}/media-{UUIDT()}",
            purpose=purpose,
            **kwargs,
        )

    @parameterized.expand(
        [
            ("missing", ""),
            # A typo would otherwise list as empty, reading as "no images yet" rather than
            # "that library does not exist".
            ("unknown", "?purpose=emial"),
        ]
    )
    def test_list_rejects_a_purpose_that_names_no_library(self, _name: str, query: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/uploaded_media/{query}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_start_upload_rejects_a_purpose_that_names_no_library(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media/start_upload/",
                {"name": "logo.png", "purpose": "emial"},
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        assert UploadedMedia.objects.count() == 0

    def test_list_returns_only_matching_purpose_for_own_team_newest_first(self) -> None:
        first = self._create_media(purpose="canvas", file_name="first.png")
        second = self._create_media(purpose="canvas", file_name="second.png")
        self._create_media(purpose=None, file_name="legacy-dashboard-image.png")
        self._create_media(purpose="something-else", file_name="other-purpose.png")

        other_team = Team.objects.create(organization=self.organization, name="other team")
        UploadedMedia.objects.create(
            team=other_team, file_name="not-mine.png", content_type="image/png", purpose="canvas"
        )

        response = self.client.get(f"/api/projects/{self.team.id}/uploaded_media/?purpose=canvas")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        payload = response.json()
        assert payload["count"] == 2
        assert [item["id"] for item in payload["results"]] == [str(second.id), str(first.id)]

        listed = payload["results"][0]
        assert listed["name"] == "second.png"
        assert listed["content_type"] == "image/png"
        assert listed["purpose"] == "canvas"
        assert listed["url"] == f"http://localhost:8010/uploaded_media/{second.id}"
        assert listed["created_at"] is not None

    @parameterized.expand(
        [
            ("with_purpose", {"purpose": "email"}, 1),
            # Existing callers (dashboard text cards, notebooks, toolbar) upload with no
            # purpose and must stay invisible to any purpose-scoped listing.
            ("without_purpose", {}, 0),
        ]
    )
    def test_create_joins_the_library_only_when_a_purpose_is_given(
        self, _name: str, extra_fields: dict, expected_count: int
    ) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media",
                    {"image": image, **extra_fields},
                    format="multipart",
                )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

            list_response = self.client.get(f"/api/projects/{self.team.id}/uploaded_media/?purpose=email")
            self.assertEqual(list_response.status_code, status.HTTP_200_OK, list_response.json())
            results = list_response.json()["results"]
            assert len(results) == expected_count
            if expected_count:
                assert results[0]["id"] == response.json()["id"]
                assert results[0]["size_bytes"] == os.path.getsize(get_path_to("a-small-but-valid.gif"))

    def test_create_rejects_an_oversized_purpose_before_writing_anything(self) -> None:
        """purpose is a varchar(100) column. Without validating it up front, an oversized value
        reaches the DB write after the row and object already exist, turning a client mistake
        into an unhandled 500 with orphaned state instead of a clean 400."""
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media",
                    {"image": image, "purpose": "x" * 101},
                    format="multipart",
                )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        assert UploadedMedia.objects.count() == 0

    def test_create_stores_sniffed_content_type_not_the_claimed_one(self) -> None:
        """A caller claiming the wrong content type must not corrupt what we store and serve —
        we sniff the real type from the bytes, so a mislabeled upload is still served correctly."""
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                mislabeled_file = SimpleUploadedFile(name="photo.png", content=image.read(), content_type="image/png")
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media",
                {"image": mislabeled_file, "purpose": "email"},
                format="multipart",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
            media_location = response.json()["image_location"]

            self.client.logout()
            download_response = self.client.get(media_location)
            assert download_response.headers["Content-Type"] == "image/gif"

    def test_start_upload_returns_a_presigned_post_and_reserves_a_pending_row(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media/start_upload/",
                {"name": "logo.png", "purpose": "canvas"},
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        payload = response.json()
        assert payload["upload_url"]
        assert isinstance(payload["form_fields"], dict)
        assert payload["expires_in"] > 0

        media = UploadedMedia.objects.get(id=payload["id"])
        assert media.pending is True
        assert media.purpose == "canvas"
        assert media.team_id == self.team.pk

    def test_start_upload_requires_name_and_purpose(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            response = self.client.post(f"/api/projects/{self.team.id}/uploaded_media/start_upload/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_start_upload_rejects_when_object_storage_is_unavailable(self) -> None:
        with override_settings(OBJECT_STORAGE_ENABLED=False):
            response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media/start_upload/",
                {"name": "logo.png", "purpose": "email"},
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        assert UploadedMedia.objects.count() == 0

    def test_pending_upload_is_not_publicly_downloadable(self) -> None:
        """The presigned window leaves bytes unvetted until complete_upload runs — a pending
        row must not be servable, or an attacker could push arbitrary content through the
        unauthenticated download route before validation ever ran."""
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            start_response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media/start_upload/",
                {"name": "logo.png", "purpose": "email"},
            )
            media_id = start_response.json()["id"]

            self.client.logout()
            download_response = self.client.get(f"/uploaded_media/{media_id}")
        assert download_response.status_code == status.HTTP_404_NOT_FOUND

    def _start_upload(self, name: str = "logo.png", purpose: str = "email") -> tuple[str, str]:
        response = self.client.post(
            f"/api/projects/{self.team.id}/uploaded_media/start_upload/",
            {"name": name, "purpose": purpose},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        media_id = response.json()["id"]
        media_location = UploadedMedia.objects.get(id=media_id).media_location
        assert media_location is not None
        return media_id, media_location

    def test_complete_upload_verifies_and_activates_the_pending_upload(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            media_id, media_location = self._start_upload()
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                gif_bytes = image.read()
            object_storage.write(media_location, gif_bytes)

            response = self.client.post(f"/api/projects/{self.team.id}/uploaded_media/{media_id}/complete_upload/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
            payload = response.json()
            assert payload["content_type"] == "image/gif"
            assert payload["size_bytes"] == len(gif_bytes)
            assert payload["url"] == f"http://localhost:8010/uploaded_media/{media_id}"

            media = UploadedMedia.objects.get(id=media_id)
            assert media.pending is False

            list_response = self.client.get(f"/api/projects/{self.team.id}/uploaded_media/?purpose=email")
            assert [item["id"] for item in list_response.json()["results"]] == [media_id]

            self.client.logout()
            download_response = self.client.get(f"/uploaded_media/{media_id}")
            assert download_response.status_code == status.HTTP_200_OK
            assert download_response.headers["Content-Type"] == "image/gif"

    def test_completing_moves_the_object_off_the_presigned_key(self) -> None:
        """The presigned POST's signature is only checked by S3 at upload time and stays
        valid until it expires (up to 15 minutes) — Django has no way to revoke it early.
        If a completed upload kept serving from that same key, anyone still holding the
        form fields could silently replace a live, already-served image at any point
        before expiry. Completing must move the bytes to a key the presigned POST was
        never signed for, so a later write to the old key lands nowhere anyone reads."""
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            media_id, presigned_key = self._start_upload()
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                original_bytes = image.read()
            object_storage.write(presigned_key, original_bytes)

            response = self.client.post(f"/api/projects/{self.team.id}/uploaded_media/{media_id}/complete_upload/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

            media = UploadedMedia.objects.get(id=media_id)
            assert media.media_location != presigned_key

            # The presigned form is still cryptographically valid; reusing it after
            # completion must not affect what's already been verified and served.
            object_storage.write(presigned_key, b"swapped-after-verification")

            self.client.logout()
            download_response = self.client.get(f"/uploaded_media/{media_id}")
            assert download_response.content == original_bytes

    def test_complete_upload_returns_400_when_object_was_never_uploaded(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            media_id, _ = self._start_upload()
            response = self.client.post(f"/api/projects/{self.team.id}/uploaded_media/{media_id}/complete_upload/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        assert UploadedMedia.objects.get(id=media_id).pending is True

    def test_complete_upload_reports_a_storage_outage_as_retryable_not_missing(self) -> None:
        """A transient storage failure must not look like 'you never uploaded a file' — that
        4xx reads as a client mistake to callers and to alerting, and hides a real outage."""
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            media_id, _ = self._start_upload()
            with patch(
                "posthog.api.uploaded_media.object_storage.read_bytes",
                side_effect=ObjectStorageError("read failed"),
            ):
                response = self.client.post(f"/api/projects/{self.team.id}/uploaded_media/{media_id}/complete_upload/")
        assert response.status_code >= 500
        assert UploadedMedia.objects.get(id=media_id).pending is True

    @parameterized.expand(
        [
            ("non_image", b"<html>not an image</html>"),
            ("oversized", b"1" * (FOUR_MEGABYTES + 1)),
        ]
    )
    def test_complete_upload_rejects_bad_bytes_and_cleans_up(self, _name: str, uploaded_bytes: bytes) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            media_id, media_location = self._start_upload()
            object_storage.write(media_location, uploaded_bytes)

            response = self.client.post(f"/api/projects/{self.team.id}/uploaded_media/{media_id}/complete_upload/")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
            assert UploadedMedia.objects.filter(id=media_id).count() == 0
            assert object_storage.read_bytes(media_location, missing_ok=True) is None

    def test_complete_upload_keeps_the_400_when_cleanup_storage_fails(self) -> None:
        # A failing delete used to escape as a 500, hiding the caller's real mistake. The row
        # stays pending so the abandoned sweep retries it, rather than being removed and
        # leaving an object nothing points at.
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            media_id, media_location = self._start_upload()
            object_storage.write(media_location, b"<html>not an image</html>")

            with patch(
                "posthog.api.uploaded_media.object_storage.delete",
                side_effect=ObjectStorageError("delete failed"),
            ):
                response = self.client.post(f"/api/projects/{self.team.id}/uploaded_media/{media_id}/complete_upload/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        assert UploadedMedia.objects.get(id=media_id).pending is True

    def test_complete_upload_stays_retryable_if_the_db_save_fails_after_copying(self) -> None:
        """The staging object must outlive the DB write that points away from it. Deleting it
        first would mean a save failure (a dropped connection, a deadlock) leaves the row
        permanently pointing at a location that no longer exists — unrecoverable, since a retry
        reads from wherever the row currently points."""
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            media_id, media_location = self._start_upload()
            with open(get_path_to("a-small-but-valid.gif"), "rb") as image:
                gif_bytes = image.read()
            object_storage.write(media_location, gif_bytes)

            with patch.object(UploadedMedia, "save", side_effect=Exception("simulated DB failure")):
                failed_response = self.client.post(
                    f"/api/projects/{self.team.id}/uploaded_media/{media_id}/complete_upload/"
                )
            assert failed_response.status_code >= 500
            assert UploadedMedia.objects.get(id=media_id).pending is True

            # Retrying without the simulated failure must still succeed — proves the staging
            # object was never deleted out from under the still-pointing-at-it row.
            retry_response = self.client.post(
                f"/api/projects/{self.team.id}/uploaded_media/{media_id}/complete_upload/"
            )
            self.assertEqual(retry_response.status_code, status.HTTP_200_OK, retry_response.json())

    def test_complete_upload_for_a_non_pending_row_returns_404(self) -> None:
        """Guards against completing (and re-validating) an already-live row twice."""
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            media_id, media_location = self._start_upload()
            object_storage.write(media_location, b"")
        UploadedMedia.objects.filter(id=media_id).update(pending=False)

        response = self.client.post(f"/api/projects/{self.team.id}/uploaded_media/{media_id}/complete_upload/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.json())

    def test_complete_upload_for_another_teams_row_returns_404(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        media = self._create_media(purpose="email", pending=True)
        media.team = other_team
        media.save(update_fields=["team"])

        response = self.client.post(f"/api/projects/{self.team.id}/uploaded_media/{media.id}/complete_upload/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.json())

    def test_start_upload_requires_uploaded_media_write_scope(self) -> None:
        """Guards against start_upload/complete_upload silently missing from
        scope_object_write_actions, which would let a read-only key upload images."""
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="read-only", user=self.user, secure_value=hash_key_value(value), scopes=["uploaded_media:read"]
        )
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/uploaded_media/start_upload/",
            {"name": "logo.png", "purpose": "email"},
            headers={"Authorization": f"Bearer {value}"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())
