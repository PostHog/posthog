from datetime import timedelta

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt


class TestExportRendererAuthentication(APIBaseTest):
    def _make_export_renderer_token(self) -> str:
        return encode_jwt(
            {"id": self.user.id},
            timedelta(minutes=5),
            PosthogJwtAudience.EXPORT_RENDERER,
        )

    def _make_impersonated_user_token(self) -> str:
        return encode_jwt(
            {"id": self.user.id},
            timedelta(minutes=5),
            PosthogJwtAudience.IMPERSONATED_USER,
        )

    def test_export_renderer_token_accepted_on_session_recordings(self):
        self.client.logout()
        token = self._make_export_renderer_token()
        response = self.client.get(
            f"/api/environments/{self.team.id}/session_recordings",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_export_renderer_token_accepted_on_heatmaps(self):
        self.client.logout()
        token = self._make_export_renderer_token()
        response = self.client.get(
            f"/api/environments/{self.team.id}/heatmaps?type=click&date_from=2024-01-01&url_exact=https://example.com&viewport_width_min=0",
            headers={"authorization": f"Bearer {token}"},
        )
        # 200 means auth succeeded (query may return empty results but that's fine)
        assert response.status_code == status.HTTP_200_OK

    def test_export_renderer_token_rejected_on_dashboards(self):
        self.client.logout()
        token = self._make_export_renderer_token()
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            headers={"authorization": f"Bearer {token}"},
        )
        # 401 or 403 — either way, the token does not grant access
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_export_renderer_token_rejected_on_insights(self):
        self.client.logout()
        token = self._make_export_renderer_token()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_impersonated_user_token_still_works_on_session_recordings(self):
        self.client.logout()
        token = self._make_impersonated_user_token()
        response = self.client.get(
            f"/api/environments/{self.team.id}/session_recordings",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_impersonated_user_token_still_works_on_dashboards(self):
        self.client.logout()
        token = self._make_impersonated_user_token()
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_expired_export_renderer_token_rejected(self):
        self.client.logout()
        token = encode_jwt(
            {"id": self.user.id},
            timedelta(seconds=-1),
            PosthogJwtAudience.EXPORT_RENDERER,
        )
        response = self.client.get(
            f"/api/environments/{self.team.id}/session_recordings",
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
