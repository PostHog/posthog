import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from oauth2_provider.models import AbstractApplication
from parameterized import parameterized

from posthog.api.oauth.cimd import fetch_and_upsert_cimd_application, get_application_by_client_id
from posthog.api.oauth.raycast_metadata import RAYCAST_SCOPES
from posthog.scopes import UNPRIVILEGED_SCOPES


def _mock_cimd_response(document: dict):
    body = json.dumps(document).encode()
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.is_redirect = False
    resp.is_permanent_redirect = False
    resp.close = MagicMock()
    resp.iter_content = MagicMock(return_value=iter([body]))
    return resp


@override_settings(SITE_URL="https://us.posthog.com")
class TestRaycastClientMetadataView(SimpleTestCase):
    def test_returns_valid_cimd_metadata(self):
        res = self.client.get("/api/oauth/raycast/client-metadata")
        assert res.status_code == 200
        assert res["Cache-Control"] == "public, max-age=3600"
        assert "application/json" in res["Content-Type"]

        data = res.json()
        assert data["client_name"] == "Raycast extension for PostHog"
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


@override_settings(SITE_URL="https://us.posthog.com")
class TestRaycastClientMetadataRegistration(APIBaseTest):
    @patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
    @patch("posthog.api.oauth.cimd.requests.get")
    def test_document_registers_through_cimd(self, mock_get, _url_mock):
        # Serve the live document back through the CIMD fetch path (the HTTP fetch
        # is patched since CIMD client_ids must be HTTPS), then assert it registers
        # as the public client this endpoint promises. Locks the contract between
        # this document and the CIMD validation rules.
        document = self.client.get("/api/oauth/raycast/client-metadata").json()
        client_id = document["client_id"]
        mock_get.return_value = _mock_cimd_response(document)

        app = fetch_and_upsert_cimd_application(client_id)

        assert app is not None
        assert app.is_cimd_client
        assert app.cimd_metadata_url == client_id
        assert app.name == "Raycast extension for PostHog"
        assert app.client_type == AbstractApplication.CLIENT_PUBLIC
        assert app.authorization_grant_type == AbstractApplication.GRANT_AUTHORIZATION_CODE
        assert app.redirect_uris == " ".join(document["redirect_uris"])
        assert set(app.scopes) == set(RAYCAST_SCOPES)
        assert app.organization is None

        # The authorize-time lookup resolves the URL-form client_id back to this app.
        assert get_application_by_client_id(client_id).pk == app.pk
