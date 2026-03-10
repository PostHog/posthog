from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration

from ee.api.vercel.vercel_connect import (
    CONNECT_COOKIE_NAME,
    CONNECT_COOKIE_SALT,
    _get_connect_cache_key,
    _validate_next_url,
)
from ee.vercel.client import OAuthTokenResponse

CACHED_SESSION_DATA = {
    "access_token": "vercel_token_123",
    "token_type": "Bearer",
    "installation_id": "icfg_connect_test",
    "user_id": "vercel_user_1",
    "team_id": "team_vercel_1",
    "configuration_id": "cfg_1",
    "next_url": "https://vercel.com/done",
}


def _seed_session(session_key: str = "test-session", data: dict | None = None) -> str:
    cache.set(_get_connect_cache_key(session_key), data or CACHED_SESSION_DATA, timeout=600)
    return session_key


def _bind_cookie(client, session_key: str) -> None:
    from django.http import HttpResponse

    response = HttpResponse()
    response.set_signed_cookie(
        CONNECT_COOKIE_NAME,
        session_key,
        salt=CONNECT_COOKIE_SALT,
        max_age=600,
    )
    raw_cookie = response.cookies[CONNECT_COOKIE_NAME].value
    client.cookies[CONNECT_COOKIE_NAME] = raw_cookie


class VercelConnectTestBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()


class TestVercelConnectCallback(VercelConnectTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/connect/vercel/callback"

    def test_missing_code_returns_400(self):
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(VERCEL_CLIENT_INTEGRATION_ID="", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
    def test_missing_client_config_returns_500(self):
        response = self.client.get(self.url, {"code": "test_code"})

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_failed_token_exchange_returns_401(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
            access_token="",
            token_type="",
            installation_id="",
            user_id="",
            error="invalid_code",
            error_description="Code expired",
        )

        response = self.client.get(self.url, {"code": "bad_code"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_successful_exchange_redirects_authenticated_user_to_link(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
            access_token="tok_123",
            token_type="Bearer",
            installation_id="icfg_new",
            user_id="usr_1",
            team_id="team_1",
        )

        response = self.client.get(self.url, {"code": "good_code", "next": "https://vercel.com/done"})

        assert response.status_code == 302
        location = response["Location"]
        assert location.startswith("/connect/vercel/link?")
        parsed = parse_qs(urlparse(location).query)
        assert "session" in parsed
        assert "next" not in parsed
        session_key = parsed["session"][0]
        cached_data = cache.get(_get_connect_cache_key(session_key))
        assert cached_data["next_url"] == "https://vercel.com/done"

    @parameterized.expand(
        [
            ("evil_domain", "https://evil.com/phish"),
            ("javascript_uri", "javascript:alert(document.cookie)"),
            ("data_uri", "data:text/html,<script>alert(1)</script>"),
            ("vbscript_uri", "vbscript:MsgBox('xss')"),
            ("protocol_relative", "//evil.com/path"),
        ]
    )
    @override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_malicious_next_url_is_rejected(self, _name, malicious_url, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
            access_token="tok_123",
            token_type="Bearer",
            installation_id="icfg_new",
            user_id="usr_1",
        )

        response = self.client.get(self.url, {"code": "good_code", "next": malicious_url})

        assert response.status_code == 302
        parsed = parse_qs(urlparse(response["Location"]).query)
        assert "next" not in parsed
        session_key = parsed["session"][0]
        cached_data = cache.get(_get_connect_cache_key(session_key))
        assert cached_data["next_url"] == ""

    @override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_unauthenticated_user_redirected_to_login(self, mock_client_class):
        self.client.logout()
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
            access_token="tok_123",
            token_type="Bearer",
            installation_id="icfg_new",
            user_id="usr_1",
        )

        response = self.client.get(self.url, {"code": "good_code"})

        assert response.status_code == 302
        assert response["Location"].startswith("/login?next=")


class TestVercelConnectSessionInfo(VercelConnectTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/api/vercel/connect/session"

    def test_missing_session_returns_400(self):
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_expired_session_returns_400(self):
        _bind_cookie(self.client, "nonexistent")

        response = self.client.get(self.url, {"session": "nonexistent"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_mismatched_cookie_returns_400(self):
        session_key = _seed_session()
        _bind_cookie(self.client, "wrong-key")

        response = self.client.get(self.url, {"session": session_key})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Session mismatch" in response.json()["detail"]

    def test_missing_cookie_returns_400(self):
        session_key = _seed_session()

        response = self.client.get(self.url, {"session": session_key})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Session mismatch" in response.json()["detail"]

    def test_returns_orgs_where_user_is_admin(self):
        session_key = _seed_session()
        _bind_cookie(self.client, session_key)

        response = self.client.get(self.url, {"session": session_key})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["next_url"] == "https://vercel.com/done"
        assert len(data["organizations"]) == 1
        assert data["organizations"][0]["name"] == self.organization.name
        assert data["organizations"][0]["already_linked"] is False

    def test_marks_already_linked_orgs(self):
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_existing",
            config={},
            created_by=self.user,
        )
        session_key = _seed_session()
        _bind_cookie(self.client, session_key)

        response = self.client.get(self.url, {"session": session_key})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["organizations"][0]["already_linked"] is True

    def test_excludes_orgs_where_user_is_member_not_admin(self):
        other_org = Organization.objects.create(name="Other Org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=other_org,
            level=OrganizationMembership.Level.MEMBER,
        )
        session_key = _seed_session()
        _bind_cookie(self.client, session_key)

        response = self.client.get(self.url, {"session": session_key})

        assert response.status_code == status.HTTP_200_OK
        org_names = [o["name"] for o in response.json()["organizations"]]
        assert "Other Org" not in org_names

    def test_unauthenticated_returns_403(self):
        self.client.logout()
        session_key = _seed_session()

        response = self.client.get(self.url, {"session": session_key})

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


class TestVercelConnectComplete(VercelConnectTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/api/vercel/connect/complete"

    def test_expired_session_returns_400(self):
        _bind_cookie(self.client, "nonexistent")

        response = self.client.post(
            self.url,
            {"session": "nonexistent", "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_successful_link_creates_integration(self):
        session_key = _seed_session()
        _bind_cookie(self.client, session_key)

        response = self.client.post(
            self.url,
            {"session": session_key, "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["status"] == "linked"
        assert data["organization_name"] == self.organization.name

        integration = OrganizationIntegration.objects.get(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        )
        assert integration.config["type"] == "connectable"
        assert integration.config["credentials"]["access_token"] == "vercel_token_123"
        assert integration.integration_id == "icfg_connect_test"

    def test_session_deleted_after_linking(self):
        session_key = _seed_session()
        _bind_cookie(self.client, session_key)

        self.client.post(
            self.url,
            {"session": session_key, "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert cache.get(_get_connect_cache_key(session_key)) is None

    def test_non_member_returns_403(self):
        other_org = Organization.objects.create(name="Not My Org")
        session_key = _seed_session()
        _bind_cookie(self.client, session_key)

        response = self.client.post(
            self.url,
            {"session": session_key, "organization_id": str(other_org.id)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_member_not_admin_returns_403(self):
        other_org = Organization.objects.create(name="Member Org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=other_org,
            level=OrganizationMembership.Level.MEMBER,
        )
        session_key = _seed_session()
        _bind_cookie(self.client, session_key)

        response = self.client.post(
            self.url,
            {"session": session_key, "organization_id": str(other_org.id)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_already_linked_org_returns_400(self):
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_existing",
            config={},
            created_by=self.user,
        )
        session_key = _seed_session()
        _bind_cookie(self.client, session_key)

        response = self.client.post(
            self.url,
            {"session": session_key, "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already has a Vercel integration" in response.json()["detail"]

    def test_unauthenticated_returns_403(self):
        self.client.logout()
        session_key = _seed_session()

        response = self.client.post(
            self.url,
            {"session": session_key, "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_mismatched_session_key_returns_400(self):
        session_key = _seed_session()
        _bind_cookie(self.client, "different-session-key")

        response = self.client.post(
            self.url,
            {"session": session_key, "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Session mismatch" in response.json()["detail"]

    def test_missing_django_session_key_returns_400(self):
        session_key = _seed_session()
        # Don't bind session — simulates attacker sending victim a crafted link

        response = self.client.post(
            self.url,
            {"session": session_key, "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Session mismatch" in response.json()["detail"]

    def test_complete_clears_binding_cookie(self):
        session_key = _seed_session()
        _bind_cookie(self.client, session_key)

        response = self.client.post(
            self.url,
            {"session": session_key, "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.cookies[CONNECT_COOKIE_NAME]["max-age"] == 0


class TestVercelConnectCookieBinding(VercelConnectTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/connect/vercel/callback"

    @override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_callback_sets_signed_cookie(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
            access_token="tok_123",
            token_type="Bearer",
            installation_id="icfg_new",
            user_id="usr_1",
            team_id="team_1",
        )

        response = self.client.get(self.url, {"code": "good_code"})

        assert response.status_code == 302
        assert CONNECT_COOKIE_NAME in response.cookies
        cookie = response.cookies[CONNECT_COOKIE_NAME]
        assert cookie["httponly"] is True
        assert cookie["samesite"] == "Lax"

    @override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_end_to_end_callback_to_complete(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
            access_token="tok_e2e",
            token_type="Bearer",
            installation_id="icfg_e2e",
            user_id="usr_e2e",
            team_id="team_e2e",
        )

        response = self.client.get(self.url, {"code": "good_code"})
        assert response.status_code == 302
        parsed = parse_qs(urlparse(response["Location"]).query)
        session_key = parsed["session"][0]

        complete_response = self.client.post(
            "/api/vercel/connect/complete",
            {"session": session_key, "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert complete_response.status_code == status.HTTP_201_CREATED
        assert complete_response.json()["status"] == "linked"

    @override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_binding_survives_session_flush(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
            access_token="tok_sso",
            token_type="Bearer",
            installation_id="icfg_sso",
            user_id="usr_sso",
            team_id="team_sso",
        )

        response = self.client.get(self.url, {"code": "good_code"})
        assert response.status_code == 302
        parsed = parse_qs(urlparse(response["Location"]).query)
        session_key = parsed["session"][0]

        # Simulate SSO login: flush destroys session, then user re-authenticates
        self.client.session.flush()
        self.client.force_login(self.user)

        complete_response = self.client.post(
            "/api/vercel/connect/complete",
            {"session": session_key, "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert complete_response.status_code == status.HTTP_201_CREATED
        assert complete_response.json()["status"] == "linked"


class TestValidateNextUrl(TestCase):
    @parameterized.expand(
        [
            ("valid_vercel", "https://vercel.com/done", "https://vercel.com/done"),
            ("valid_www_vercel", "https://www.vercel.com/path", "https://www.vercel.com/path"),
            ("http_vercel", "http://vercel.com/path", "http://vercel.com/path"),
            ("empty_string", "", ""),
            ("javascript_uri", "javascript:alert(1)", ""),
            ("data_uri", "data:text/html,<script>alert(1)</script>", ""),
            ("vbscript_uri", "vbscript:MsgBox('xss')", ""),
            ("evil_domain", "https://evil.com/phish", ""),
            ("protocol_relative", "//evil.com", ""),
            ("mixed_case_scheme", "JavaScript:alert(1)", ""),
            ("ftp_scheme", "ftp://vercel.com/file", ""),
            ("no_hostname", "https://", ""),
        ]
    )
    def test_validate_next_url(self, _name, url, expected):
        assert _validate_next_url(url) == expected
