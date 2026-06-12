from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.api.oauth.raycast_metadata import RAYCAST_SCOPES
from posthog.scopes import UNPRIVILEGED_SCOPES


@override_settings(SITE_URL="https://us.posthog.com")
class TestRaycastClientMetadataView(SimpleTestCase):
    def test_returns_valid_cimd_metadata(self):
        res = self.client.get("/api/oauth/raycast/client-metadata")
        assert res.status_code == 200
        assert res["Cache-Control"] == "public, max-age=3600"
        assert "application/json" in res["Content-Type"]

        data = res.json()
        assert data["client_name"] == "Raycast"
        assert data["redirect_uris"] == [
            "https://raycast.com/redirect?packageName=Extension",
            "https://raycast.com/redirect?packageName=posthog",
        ]
        assert data["grant_types"] == ["authorization_code"]
        assert data["response_types"] == ["code"]
        assert data["token_endpoint_auth_method"] == "none"
        assert data["com.posthog"]["scopes"] == RAYCAST_SCOPES

    @parameterized.expand(
        [
            ("https://us.posthog.com", "https://us.posthog.com/api/oauth/raycast/client-metadata"),
            ("https://eu.posthog.com", "https://eu.posthog.com/api/oauth/raycast/client-metadata"),
        ]
    )
    def test_client_id_is_built_from_site_url(self, site_url: str, expected_client_id: str):
        with override_settings(SITE_URL=site_url):
            res = self.client.get("/api/oauth/raycast/client-metadata")
        assert res.json()["client_id"] == expected_client_id

    def test_declared_scopes_are_unprivileged(self):
        # A scope falling out of UNPRIVILEGED_SCOPES would make CIMD registration
        # reject the metadata document outright (see _resolve_scopes in cimd.py).
        assert set(RAYCAST_SCOPES) <= set(UNPRIVILEGED_SCOPES)

    def test_post_not_allowed(self):
        res = self.client.post("/api/oauth/raycast/client-metadata")
        assert res.status_code == 405
