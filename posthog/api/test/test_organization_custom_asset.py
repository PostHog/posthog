import os

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.admin.inlines.organization_custom_asset_inline import OrganizationCustomAssetInlineForm
from posthog.models import OrganizationCustomAsset
from posthog.models.organization import OrganizationMembership
from posthog.models.uploaded_media import ObjectStorageUnavailable
from posthog.models.utils import uuid7


class TestOrganizationCustomAsset(APIBaseTest):
    def _create_asset(
        self,
        *,
        key: str = "logo",
        content_type: str | None = "image/png",
        media_location: str | None = "media_uploads/organization-1/custom-asset-x",
        file_name: str | None = "logo.png",
    ) -> OrganizationCustomAsset:
        return OrganizationCustomAsset.objects.create(
            organization=self.organization,
            created_by=self.user,
            key=key,
            content_type=content_type,
            media_location=media_location,
            file_name=file_name,
        )

    def test_save_content_writes_to_object_storage_and_sets_media_location(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER="test-folder"):
            with patch("posthog.models.organization_custom_asset.object_storage.write") as mock_write:
                asset = OrganizationCustomAsset.save_content(
                    organization=self.organization,
                    created_by=self.user,
                    key="hog",
                    file_name="hog.png",
                    content_type="image/png",
                    content=b"image-bytes",
                )

        assert asset is not None
        expected_path = f"test-folder/organization-{self.organization.pk}/custom-asset-{asset.pk}"
        assert asset.media_location == expected_path
        assert asset.key == "hog"
        mock_write.assert_called_once_with(expected_path, b"image-bytes")

    def test_save_content_raises_when_object_storage_unavailable(self) -> None:
        with override_settings(OBJECT_STORAGE_ENABLED=False):
            with self.assertRaises(ObjectStorageUnavailable):
                OrganizationCustomAsset.save_content(
                    organization=self.organization,
                    created_by=self.user,
                    key="hog",
                    file_name="hog.png",
                    content_type="image/png",
                    content=b"image-bytes",
                )

    def test_download_returns_image_with_immutable_cache(self) -> None:
        asset = self._create_asset(content_type="image/png")
        self.client.logout()

        with patch(
            "posthog.api.organization_custom_asset.object_storage.read_bytes",
            return_value=b"the-image-bytes",
        ):
            response = self.client.get(f"/organization_custom_asset/{asset.id}")

        assert response.status_code == status.HTTP_200_OK
        assert response.content == b"the-image-bytes"
        assert response.headers["Content-Type"] == "image/png"
        assert response.headers["Cache-Control"] == "public, max-age=315360000, immutable"

    def test_download_unknown_id_returns_404(self) -> None:
        self.client.logout()
        response = self.client.get(f"/organization_custom_asset/{uuid7()}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_download_invalid_uuid_returns_404(self) -> None:
        self.client.logout()
        response = self.client.get("/organization_custom_asset/not-a-valid-uuid")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_download_missing_media_location_returns_404(self) -> None:
        asset = self._create_asset(media_location=None)
        self.client.logout()
        response = self.client.get(f"/organization_custom_asset/{asset.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("png", "image/png", True),
            ("jpeg", "image/jpeg", True),
            ("gif", "image/gif", True),
            ("webp", "image/webp", True),
            ("html", "text/html", False),
            ("svg", "image/svg+xml", False),
            ("javascript", "application/javascript", False),
        ]
    )
    def test_download_inline_vs_attachment(self, _name: str, content_type: str, inline: bool) -> None:
        asset = self._create_asset(content_type=content_type)
        self.client.logout()

        with patch(
            "posthog.api.organization_custom_asset.object_storage.read_bytes",
            return_value=b"bytes",
        ):
            response = self.client.get(f"/organization_custom_asset/{asset.id}")

        assert response.status_code == status.HTTP_200_OK
        if inline:
            assert response.headers["Content-Type"] == content_type
            assert "attachment" not in response.headers.get("Content-Disposition", "")
        else:
            assert response.headers["Content-Type"].startswith("application/octet-stream")
            assert response.headers.get("Content-Disposition", "").startswith("attachment")

    def test_organization_api_exposes_custom_assets(self) -> None:
        asset = self._create_asset(key="logo", file_name="logo.png")

        response = self.client.get("/api/organizations/@current")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert "custom_assets" in data
        assert len(data["custom_assets"]) == 1
        returned = data["custom_assets"][0]
        assert returned["id"] == str(asset.id)
        assert returned["key"] == "logo"
        assert returned["file_name"] == "logo.png"
        assert returned["url"].endswith(f"/organization_custom_asset/{asset.id}")

    def test_custom_assets_cannot_be_written_via_api(self) -> None:
        # Even an org owner cannot create assets through the API — it is a read-only field.
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        response = self.client.patch(
            f"/api/organizations/{self.organization.id}",
            {"custom_assets": [{"key": "injected", "url": "http://evil", "file_name": "x.png"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["custom_assets"] == []
        assert OrganizationCustomAsset.objects.filter(organization=self.organization).count() == 0

    def test_admin_inline_form_rejects_non_image_upload(self) -> None:
        form = OrganizationCustomAssetInlineForm(
            data={"key": "logo"},
            files={"image": SimpleUploadedFile("not-an-image.csv", b"a,b,c", content_type="text/csv")},
        )
        assert not form.is_valid()
        assert "image" in form.errors

    def test_admin_inline_form_requires_image_for_new_asset(self) -> None:
        form = OrganizationCustomAssetInlineForm(data={"key": "logo"}, files={})
        assert not form.is_valid()
        assert "image" in form.errors

    def test_admin_inline_form_rejects_image_when_object_storage_disabled(self) -> None:
        # A valid image that would otherwise pass — it must be rejected so no asset row is saved
        # without retrievable media when object storage is unavailable.
        fixture = os.path.join(os.path.dirname(__file__), "fixtures", "a-small-but-valid.gif")
        with open(fixture, "rb") as f:
            image = SimpleUploadedFile("logo.gif", f.read(), content_type="image/gif")
        with override_settings(OBJECT_STORAGE_ENABLED=False):
            form = OrganizationCustomAssetInlineForm(data={"key": "logo"}, files={"image": image})
            assert not form.is_valid()
            assert "image" in form.errors
