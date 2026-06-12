from django.test import SimpleTestCase, override_settings

from posthog.api.oauth.raycast_metadata import RAYCAST_SCOPES
from posthog.scopes import UNPRIVILEGED_SCOPES


@override_settings(SITE_URL="https://us.posthog.com")
class TestRaycastClientMetadataView(SimpleTestCase):
    def test_returns_valid_cimd_metadata(self):
        res = self.client.get("/api/oauth/raycast/client-metadata")
        assert res.status_code == 200
        data = res.json()

        assert data["client_id"] == "https://us.posthog.com/api/oauth/raycast/client-metadata"
        assert data["client_name"] == "Raycast"
        assert data["redirect_uris"] == [
            "https://raycast.com/redirect?packageName=Extension",
            "https://raycast.com/redirect?packageName=posthog",
        ]
        assert data["grant_types"] == ["authorization_code"]
        assert data["response_types"] == ["code"]
        assert data["token_endpoint_auth_method"] == "none"
        assert data["com.posthog"]["scopes"] == RAYCAST_SCOPES

    def test_client_id_matches_hosted_path(self):
        res = self.client.get("/api/oauth/raycast/client-metadata")
        data = res.json()
        assert data["client_id"].endswith("/api/oauth/raycast/client-metadata")

    @override_settings(SITE_URL="https://eu.posthog.com")
    def test_client_id_uses_site_url_for_eu(self):
        res = self.client.get("/api/oauth/raycast/client-metadata")
        data = res.json()
        assert data["client_id"] == "https://eu.posthog.com/api/oauth/raycast/client-metadata"

    def test_declared_scopes_are_unprivileged(self):
        # A scope falling out of UNPRIVILEGED_SCOPES would make CIMD registration
        # reject the metadata document outright (see _resolve_scopes in cimd.py).
        assert set(RAYCAST_SCOPES) <= set(UNPRIVILEGED_SCOPES)

    def test_cache_control_header_set(self):
        res = self.client.get("/api/oauth/raycast/client-metadata")
        assert res["Cache-Control"] == "public, max-age=3600"

    def test_content_type_is_json(self):
        res = self.client.get("/api/oauth/raycast/client-metadata")
        assert "application/json" in res["Content-Type"]

    def test_post_not_allowed(self):
        res = self.client.post("/api/oauth/raycast/client-metadata")
        assert res.status_code == 405
