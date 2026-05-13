from django.test import SimpleTestCase, override_settings

from parameterized import parameterized


@override_settings(SITE_URL="https://us.posthog.com")
class TestDefinitionsClientMetadataView(SimpleTestCase):
    def test_returns_region_agnostic_metadata_fields(self):
        res = self.client.get("/api/oauth/posthog-definitions/client-metadata")
        assert res.status_code == 200
        data = res.json()

        assert data["client_name"] == "posthog-definitions"
        assert data["redirect_uris"] == ["http://localhost/callback"]
        assert data["grant_types"] == ["authorization_code", "refresh_token"]
        assert data["response_types"] == ["code"]
        assert data["token_endpoint_auth_method"] == "none"

    @parameterized.expand(
        [
            ("https://us.posthog.com",),
            ("https://eu.posthog.com",),
        ]
    )
    def test_client_id_reflects_site_url(self, site_url: str):
        with override_settings(SITE_URL=site_url):
            res = self.client.get("/api/oauth/posthog-definitions/client-metadata")
            assert res.json()["client_id"] == f"{site_url}/api/oauth/posthog-definitions/client-metadata"

    def test_cache_control_header_set(self):
        res = self.client.get("/api/oauth/posthog-definitions/client-metadata")
        assert res["Cache-Control"] == "public, max-age=3600"

    def test_content_type_is_json(self):
        res = self.client.get("/api/oauth/posthog-definitions/client-metadata")
        assert "application/json" in res["Content-Type"]

    def test_post_not_allowed(self):
        res = self.client.post("/api/oauth/posthog-definitions/client-metadata")
        assert res.status_code == 405
