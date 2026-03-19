from datetime import timedelta

from posthog.test.base import APIBaseTest

from rest_framework import status
from rest_framework.test import APIClient

from posthog.jwt import PosthogJwtAudience, encode_jwt


class TestExportRendererAuthentication(APIBaseTest):
    def _make_export_renderer_token(self) -> str:
        return encode_jwt(
            {"id": self.user.id},
            timedelta(minutes=5),
            PosthogJwtAudience.EXPORT_RENDERER,
        )

    @staticmethod
    def _unauthenticated_client() -> APIClient:
        return APIClient()

    def test_export_renderer_token_accepted_on_session_recordings(self):
        client = self._unauthenticated_client()
        token = self._make_export_renderer_token()
        response = client.get(
            f"/api/environments/{self.team.id}/session_recordings",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_export_renderer_token_accepted_on_heatmaps(self):
        client = self._unauthenticated_client()
        token = self._make_export_renderer_token()
        response = client.get(
            f"/api/environments/{self.team.id}/heatmaps?type=click&date_from=2024-01-01&url_exact=https://example.com&viewport_width_min=0",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_export_renderer_token_rejected_on_dashboards(self):
        client = self._unauthenticated_client()
        token = self._make_export_renderer_token()
        response = client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_export_renderer_token_rejected_on_user_api(self):
        client = self._unauthenticated_client()
        token = self._make_export_renderer_token()
        response = client.get(
            "/api/users/@me/",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_expired_export_renderer_token_rejected(self):
        client = self._unauthenticated_client()
        token = encode_jwt(
            {"id": self.user.id},
            timedelta(seconds=-1),
            PosthogJwtAudience.EXPORT_RENDERER,
        )
        response = client.get(
            f"/api/environments/{self.team.id}/session_recordings",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
