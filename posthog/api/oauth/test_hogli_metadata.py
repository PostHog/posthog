import json
from ipaddress import ip_address
from urllib.parse import urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from oauth2_provider.models import AbstractApplication
from parameterized import parameterized

from posthog.api.oauth.cimd import fetch_and_upsert_cimd_application, get_application_by_client_id
from posthog.api.oauth.hogli_metadata import HOGLI_LOGO_URI, HOGLI_SCOPES
from posthog.models.oauth import is_loopback_host
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
class TestHogliClientMetadataView(SimpleTestCase):
    def test_returns_valid_cimd_metadata(self):
        res = self.client.get("/api/oauth/hogli/client-metadata")
        assert res.status_code == 200
        assert res["Cache-Control"] == "public, max-age=3600"
        assert "application/json" in res["Content-Type"]

        data = res.json()
        assert data["client_name"] == "hogli CLI for PostHog"
        assert data["redirect_uris"] == ["http://127.0.0.1/callback"]
        assert data["grant_types"] == ["authorization_code", "refresh_token"]
        assert data["response_types"] == ["code"]
        assert data["token_endpoint_auth_method"] == "none"
        assert data["com.posthog"]["scopes"] == HOGLI_SCOPES

    @parameterized.expand(
        [
            ("https://us.posthog.com", "https://us.posthog.com/api/oauth/hogli/client-metadata"),
            ("https://eu.posthog.com", "https://eu.posthog.com/api/oauth/hogli/client-metadata"),
        ]
    )
    def test_client_id_is_built_from_site_url(self, site_url: str, expected_client_id: str):
        # hogli derives the same URL from whichever host it talks to, so a self-hosted
        # instance resolves its own document with no client registered for it.
        with override_settings(SITE_URL=site_url):
            res = self.client.get("/api/oauth/hogli/client-metadata")
        assert res.json()["client_id"] == expected_client_id

    def test_declared_scopes_are_unprivileged(self):
        # A scope outside this set makes CIMD reject the whole document (cimd.py, _resolve_scopes).
        assert set(HOGLI_SCOPES) <= set(UNPRIVILEGED_SCOPES)

    def test_redirect_is_a_portless_loopback_uri(self):
        # The registered *host* is the binding part: hogli must redirect to 127.0.0.1, because a
        # `localhost` request against this registration is rejected. The port is not load-bearing
        # either way (the port check is waived for a registered loopback literal, with or without
        # one), so portless is a convention that says so rather than a requirement.
        [redirect] = self.client.get("/api/oauth/hogli/client-metadata").json()["redirect_uris"]
        parsed = urlparse(redirect)
        assert parsed.scheme == "http"
        assert parsed.hostname == "127.0.0.1"
        assert parsed.port is None
        assert is_loopback_host(parsed.hostname)

    def test_logo_is_https_so_cimd_keeps_it(self):
        # cimd.py drops a non-HTTPS logo_uri instead of failing, shipping a logo-less screen.
        logo = self.client.get("/api/oauth/hogli/client-metadata").json()["logo_uri"]
        assert logo == HOGLI_LOGO_URI and logo.startswith("https://")

    def test_post_not_allowed(self):
        res = self.client.post("/api/oauth/hogli/client-metadata")
        assert res.status_code == 405


@override_settings(SITE_URL="https://us.posthog.com")
class TestHogliClientMetadataRegistration(APIBaseTest):
    @patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_document_registers_through_cimd(self, mock_get, _url_mock):
        # Serve the live document back through the CIMD fetch path, so the document and the
        # CIMD validation rules cannot drift apart. The fetch is patched because client_ids
        # must be HTTPS.
        document = self.client.get("/api/oauth/hogli/client-metadata").json()
        client_id = document["client_id"]
        mock_get.return_value = _mock_cimd_response(document)

        app = fetch_and_upsert_cimd_application(client_id)

        assert app is not None
        assert app.is_cimd_client
        assert app.cimd_metadata_url == client_id
        assert app.name == "hogli CLI for PostHog"
        assert app.client_type == AbstractApplication.CLIENT_PUBLIC
        assert app.authorization_grant_type == AbstractApplication.GRANT_AUTHORIZATION_CODE
        assert app.redirect_uris == " ".join(document["redirect_uris"])
        assert set(app.scopes) == set(HOGLI_SCOPES)
        assert app.logo_uri == HOGLI_LOGO_URI

        assert get_application_by_client_id(client_id).pk == app.pk

    @patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
    @patch("posthog.api.oauth.cimd.requests.Session.get")
    def test_registration_leaves_verification_to_a_human(self, mock_get, _url_mock):
        # Registration must not self-certify: the unverified warning only means something
        # while `is_verified` stays staff-set.
        document = self.client.get("/api/oauth/hogli/client-metadata").json()
        mock_get.return_value = _mock_cimd_response(document)

        app = fetch_and_upsert_cimd_application(document["client_id"])

        assert app is not None
        assert app.is_verified is False
        assert app.skip_authorization is False
