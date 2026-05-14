from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status


class TestSdkDoctorViewSet(APIBaseTest):
    """Tests for the /api/projects/{team_id}/sdk_doctor/report/ MCP-accessible endpoint."""

    def _url(self) -> str:
        return f"/api/projects/{self.team.pk}/sdk_doctor/report/"

    def test_requires_authentication(self) -> None:
        self.client.logout()
        response = self.client.get(self._url())
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @patch("posthog.api.sdk_doctor.get_team_data")
    @patch("posthog.api.sdk_doctor.get_github_sdk_data")
    def test_cold_cache_returns_empty_healthy_report(self, mock_github, mock_team) -> None:
        # Both caches cold → endpoint must still respond 200 with a healthy (but empty) report
        # rather than a 500 — agents should see "nothing to report" not a service error.
        mock_team.return_value = None
        mock_github.return_value = {}

        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["overall_health"] == "healthy"
        assert data["health"] == "success"
        assert data["needs_updating_count"] == 0
        assert data["team_sdk_count"] == 0
        assert data["sdks"] == []

    @patch("posthog.api.sdk_doctor.get_team_data")
    @patch("posthog.api.sdk_doctor.get_github_sdk_data")
    def test_happy_path_returns_digested_report(self, mock_github, mock_team) -> None:
        mock_team.return_value = {
            "posthog-node": [
                {
                    "lib_version": "1.0.0",
                    "count": 100,
                    "max_timestamp": "2026-04-21T00:00:00Z",
                }
            ]
        }
        mock_github.return_value = {
            "posthog-node": {
                "latestVersion": "2.0.0",
                "releaseDates": {"1.0.0": "2025-10-01T00:00:00Z"},
            }
        }

        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["team_sdk_count"] == 1
        assert data["needs_updating_count"] == 1
        assert data["overall_health"] == "needs_attention"
        sdk = data["sdks"][0]
        assert sdk["lib"] == "posthog-node"
        assert sdk["readable_name"] == "Node.js"
        assert sdk["is_outdated"] is True
        # UI-parity fields must round-trip through the serializer
        release = sdk["releases"][0]
        assert release["status_reason"].startswith("Released ")
        assert "posthog-node" in release["sql_query"]
        assert release["activity_page_url"].startswith(f"/project/{self.team.pk}/")

    @patch("posthog.api.sdk_doctor.get_team_data")
    @patch("posthog.api.sdk_doctor.get_github_sdk_data")
    def test_force_refresh_param_threaded_to_fetcher(self, mock_github, mock_team) -> None:
        mock_team.return_value = None
        mock_github.return_value = {}
        self.client.get(self._url() + "?force_refresh=true")
        assert mock_team.called
        # Accept either positional or keyword form so this test survives a future
        # refactor from get_team_data(team_id, force_refresh) to ...(team_id, force_refresh=...)
        args, kwargs = mock_team.call_args
        force_refresh = kwargs.get("force_refresh", args[1] if len(args) > 1 else None)
        assert force_refresh is True

    @patch("posthog.api.sdk_doctor.get_team_data")
    @patch("posthog.api.sdk_doctor.get_github_sdk_data")
    def test_partial_cache_missing_sdk_in_github_data_is_skipped(self, mock_github, mock_team) -> None:
        # team_data has two SDKs, but github cache only knows about one.
        # The defensive `.get(lib, {})` in SdkDoctorViewSet.report is what makes this safe —
        # compute_sdk_health skips SDKs with no latest_version rather than KeyError.
        # If someone ever swaps `.get(lib, {})` back to `sdk_data[lib]` (like the legacy
        # flat endpoint does), this test will catch it.
        mock_team.return_value = {
            "posthog-node": [{"lib_version": "1.0.0", "count": 100, "max_timestamp": "2026-04-21T00:00:00Z"}],
            "posthog-python": [{"lib_version": "7.0.0", "count": 50, "max_timestamp": "2026-04-21T00:00:00Z"}],
        }
        mock_github.return_value = {
            "posthog-node": {
                "latestVersion": "2.0.0",
                "releaseDates": {"1.0.0": "2025-10-01T00:00:00Z"},
            }
            # posthog-python deliberately absent
        }

        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Only the SDK with matching github data should be reported
        assert data["team_sdk_count"] == 1
        sdk_libs = [s["lib"] for s in data["sdks"]]
        assert sdk_libs == ["posthog-node"]
        assert "posthog-python" not in sdk_libs
