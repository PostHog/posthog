from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

HASH = "a" * 64


class TestAIBlobEndpoint(APIBaseTest):
    def _url(self, team_id: int | None = None, hash: str = HASH) -> str:
        return f"/api/projects/{team_id or self.team.pk}/ai_blob/v1/sha256/{hash}"

    @patch("products.ai_observability.backend.api.ai_blob.object_storage.read_object")
    def test_serves_inline_image_with_immutable_caching(self, mock_read) -> None:
        mock_read.return_value = (b"png-bytes", "image/png")
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.content == b"png-bytes"
        assert response["Content-Type"] == "image/png"
        assert response["Cache-Control"] == "private, max-age=86400, immutable"
        assert response["ETag"] == f'"{HASH}"'
        assert response["X-Content-Type-Options"] == "nosniff"
        assert mock_read.call_args.args[0] == f"aio/{self.team.pk}/sha256/{HASH}"
        assert mock_read.call_args.kwargs["bucket"] == "ai-blobs"

    @parameterized.expand(
        [
            ("image/heic", "image/heic", None),
            ("image/heif", "image/heif", None),
            ("image/avif", "image/avif", None),
            ("image/svg+xml", "application/octet-stream", "attachment"),
            ("application/pdf", "application/octet-stream", "attachment"),
        ]
    )
    @patch("products.ai_observability.backend.api.ai_blob.object_storage.read_object")
    def test_disposition_follows_stored_mime(
        self, stored_mime: str, expected_content_type: str, expected_disposition: str | None, mock_read
    ) -> None:
        mock_read.return_value = (b"blob-bytes", stored_mime)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == expected_content_type
        assert response.headers.get("Content-Disposition") == expected_disposition

    @patch("products.ai_observability.backend.api.ai_blob.object_storage.read_object")
    def test_missing_object_is_404(self, mock_read) -> None:
        mock_read.return_value = None
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND

    def test_bad_hash_is_404_via_routing(self) -> None:
        assert self.client.get(self._url(hash="zz" * 32)).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self._url(hash="abc")).status_code == status.HTTP_404_NOT_FOUND

    def test_other_team_is_denied(self) -> None:
        other_team = self.create_team_with_organization(organization=self.create_organization_with_features([]))
        response = self.client.get(self._url(team_id=other_team.pk))
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_is_denied(self) -> None:
        self.client.logout()
        response = self.client.get(self._url())
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
