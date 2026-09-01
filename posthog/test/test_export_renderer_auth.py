from datetime import timedelta

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.team import Team

from products.exports.backend.models.exported_asset import ExportedAsset


class TestExportRendererAuthentication(APIBaseTest):
    def _make_export_renderer_token(
        self,
        *,
        team: Team | None = None,
        scope: str = "heatmap:read",
        export_context: dict[str, object] | None = None,
    ) -> str:
        team = team or self.team
        if export_context is None:
            export_context = (
                {"session_recording_id": "test-recording"}
                if scope == "session_recording:read"
                else {
                    "heatmap_url": "https://example.com",
                    "heatmap_data_url": "https://example.com",
                    "heatmap_type": "click",
                    "width": 1400,
                    "common_filters": {"date_from": "-7d"},
                    "heatmap_filters": {"type": "click", "aggregation": "total_count", "viewportAccuracy": 0.9},
                }
            )
        asset = ExportedAsset.objects.create(
            team=team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context=export_context,
        )
        return encode_jwt(
            {
                "id": self.user.id,
                "team_id": team.id,
                "exported_asset_id": asset.id,
                "scopes": [scope],
            },
            timedelta(minutes=5),
            PosthogJwtAudience.EXPORT_RENDERER,
        )

    def _heatmap_url(self, target_url: str = "https://example.com") -> str:
        return (
            f"/api/environments/{self.team.id}/heatmaps?type=click&date_from=-7d"
            f"&url_exact={target_url}&viewport_width_min=1260&viewport_width_max=1540"
            "&aggregation=total_count&limit=0"
        )

    @staticmethod
    def _unauthenticated_client() -> APIClient:
        return APIClient()

    @parameterized.expand(
        [
            (
                "session_recording",
                "/api/environments/{team_id}/session_recordings/test-recording",
                "session_recording:read",
            ),
            (
                "heatmaps",
                "/api/environments/{team_id}/heatmaps?type=click&date_from=-7d&url_exact=https://example.com&viewport_width_min=1260&viewport_width_max=1540&aggregation=total_count&limit=0",
                "heatmap:read",
            ),
        ]
    )
    def test_export_renderer_token_accepted_on_opted_in_endpoint(self, _name: str, url_template: str, scope: str):
        client = self._unauthenticated_client()
        token = self._make_export_renderer_token(scope=scope)
        response = client.get(
            url_template.format(team_id=self.team.id),
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code not in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}

    @parameterized.expand(
        [
            ("recording_list", "/api/environments/{team_id}/session_recordings"),
            ("different_recording", "/api/environments/{team_id}/session_recordings/another-recording"),
        ]
    )
    def test_recording_token_rejected_for_another_resource(self, _name: str, url_template: str) -> None:
        token = self._make_export_renderer_token(scope="session_recording:read")
        response = self._unauthenticated_client().get(
            url_template.format(team_id=self.team.id),
            headers={"authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_heatmap_token_rejected_for_another_query(self) -> None:
        token = self._make_export_renderer_token()
        for url in (
            self._heatmap_url("https://other.example.com"),
            self._heatmap_url().replace("date_from=-7d", "date_from=-30d"),
        ):
            with self.subTest(url=url):
                response = self._unauthenticated_client().get(
                    url,
                    headers={"authorization": f"Bearer {token}"},
                )
                assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_export_renderer_token_rejected_on_another_team(self):
        other_team = self.create_team_with_organization(self.organization)
        client = self._unauthenticated_client()
        token = self._make_export_renderer_token()

        response = client.get(
            f"/api/environments/{other_team.id}/heatmaps?type=click&date_from=2024-01-01&url_exact=https://example.com&viewport_width_min=0",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_export_renderer_token_without_asset_scope_rejected(self):
        client = self._unauthenticated_client()
        token = encode_jwt(
            {"id": self.user.id},
            timedelta(minutes=5),
            PosthogJwtAudience.EXPORT_RENDERER,
        )

        response = client.get(
            f"/api/environments/{self.team.id}/heatmaps?type=click&date_from=2024-01-01&url_exact=https://example.com&viewport_width_min=0",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

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
