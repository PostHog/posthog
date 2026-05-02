from django.test import SimpleTestCase, override_settings


@override_settings(SITE_URL="https://us.posthog.com")
class TestWizardClientMetadataView(SimpleTestCase):
    def test_returns_valid_cimd_metadata(self):
        res = self.client.get("/api/oauth/wizard/client-metadata")
        assert res.status_code == 200
        data = res.json()

        assert data["client_id"] == "https://us.posthog.com/api/oauth/wizard/client-metadata"
        assert data["client_name"] == "PostHog Wizard"
        assert data["redirect_uris"] == ["http://localhost:8239/callback"]
        assert data["grant_types"] == ["authorization_code"]
        assert data["response_types"] == ["code"]
        assert data["token_endpoint_auth_method"] == "none"

    def test_client_id_matches_hosted_path(self):
        res = self.client.get("/api/oauth/wizard/client-metadata")
        data = res.json()
        assert data["client_id"].endswith("/api/oauth/wizard/client-metadata")

    @override_settings(SITE_URL="https://eu.posthog.com")
    def test_client_id_uses_site_url_for_eu(self):
        res = self.client.get("/api/oauth/wizard/client-metadata")
        data = res.json()
        assert data["client_id"] == "https://eu.posthog.com/api/oauth/wizard/client-metadata"

    def test_cache_control_header_set(self):
        res = self.client.get("/api/oauth/wizard/client-metadata")
        assert res["Cache-Control"] == "public, max-age=3600"

    def test_content_type_is_json(self):
        res = self.client.get("/api/oauth/wizard/client-metadata")
        assert "application/json" in res["Content-Type"]

    def test_post_not_allowed(self):
        res = self.client.post("/api/oauth/wizard/client-metadata")
        assert res.status_code == 405
