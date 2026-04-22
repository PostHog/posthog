from datetime import timedelta

from posthog.test.base import APIBaseTest

from parameterized import parameterized
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

    @parameterized.expand(
        [
            ("session_recordings", "/api/environments/{team_id}/session_recordings"),
            (
                "heatmaps",
                "/api/environments/{team_id}/heatmaps?type=click&date_from=2024-01-01&url_exact=https://example.com&viewport_width_min=0",
            ),
        ]
    )
    def test_export_renderer_token_accepted_on_opted_in_endpoint(self, _name: str, url_template: str):
        client = self._unauthenticated_client()
        token = self._make_export_renderer_token()
        response = client.get(
            url_template.format(team_id=self.team.id),
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_200_OK

    @parameterized.expand(
        [
            ("dashboards", "/api/projects/{team_id}/dashboards/"),
            ("user_api", "/api/users/@me/"),
        ]
    )
    def test_export_renderer_token_rejected_on_non_opted_in_endpoint(self, _name: str, url_template: str):
        client = self._unauthenticated_client()
        token = self._make_export_renderer_token()
        response = client.get(
            url_template.format(team_id=self.team.id),
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand(
        [
            ("post",),
            ("put",),
            ("patch",),
            ("delete",),
        ]
    )
    def test_export_renderer_token_rejected_for_write_method(self, method: str):
        client = self._unauthenticated_client()
        token = self._make_export_renderer_token()
        response = getattr(client, method)(
            f"/api/environments/{self.team.id}/session_recordings",
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
