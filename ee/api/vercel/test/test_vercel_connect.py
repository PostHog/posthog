from http.cookies import Morsel
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.http import HttpResponse
from django.test import Client, TestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team

from ee.api.vercel.crypto import encrypt_payload
from ee.api.vercel.vercel_connect import (
    CONNECT_NONCE_COOKIE_PREFIX,
    CONNECT_SALT,
    _browser_nonce_cookie_name,
    _delete_orphaned_integration,
    _load_connect_session,
    _sign_connect_session,
    _validate_next_url,
)
from ee.vercel.client import OAuthTokenResponse, OperationResult

# Hardcoded independently of ee.vercel.integration.CLIENT_ENV_PREFIXES so a dropped prefix fails these tests.
EXPECTED_ENV_PREFIXES = ["NEXT_PUBLIC_", "VITE_", "NUXT_PUBLIC_", "PUBLIC_"]

CACHED_SESSION_DATA = {
    "access_token": "vercel_token_123",
    "token_type": "Bearer",
    "installation_id": "icfg_connect_test",
    "user_id": "vercel_user_1",
    "team_id": "team_vercel_1",
    "configuration_id": "cfg_1",
    "next_url": "https://vercel.com/done",
}

BROWSER_NONCE = "nonce-set-in-this-browser"
OTHER_BROWSER_NONCE = "nonce-from-another-linking-flow"
REJECTED_BROWSER_COOKIES = [("missing_cookie", None), ("cookie_from_another_flow", OTHER_BROWSER_NONCE)]
REJECTED_SESSIONS = [
    ("missing_cookie", BROWSER_NONCE, None, None, "missing_cookie"),
    ("cookie_from_another_flow", BROWSER_NONCE, OTHER_BROWSER_NONCE, OTHER_BROWSER_NONCE, "missing_cookie"),
    ("tampered_cookie", BROWSER_NONCE, BROWSER_NONCE, OTHER_BROWSER_NONCE, "nonce_mismatch"),
    ("token_without_nonce", None, BROWSER_NONCE, BROWSER_NONCE, "token_without_nonce"),
]


def _session_token_from_redirect(location: str) -> str:
    query = parse_qs(urlparse(location).query)
    if "next" in query:
        query = parse_qs(urlparse(query["next"][0]).query)
    return query["session"][0]


def _mock_vercel_client(mock_client_class: MagicMock) -> MagicMock:
    mock_client = mock_client_class.return_value
    mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
        access_token="tok_e2e",
        token_type="Bearer",
        installation_id="icfg_e2e",
        user_id="usr_e2e",
        team_id="team_e2e",
    )
    mock_client.import_resource.return_value = OperationResult(success=True)
    return mock_client


def _flow_cookie(response: HttpResponse) -> Morsel:
    [cookie] = [cookie for name, cookie in response.cookies.items() if name.startswith(CONNECT_NONCE_COOKIE_PREFIX)]
    return cookie


class VercelConnectTestBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _seed_session(self) -> str:
        self._set_nonce_cookie(BROWSER_NONCE)
        return _sign_connect_session(CACHED_SESSION_DATA, browser_nonce=BROWSER_NONCE)

    def _set_nonce_cookie(self, flow_nonce: str | None, value: str | None = None) -> None:
        for name in [name for name in self.client.cookies if name.startswith(CONNECT_NONCE_COOKIE_PREFIX)]:
            del self.client.cookies[name]
        if flow_nonce is not None:
            self.client.cookies[_browser_nonce_cookie_name(flow_nonce)] = value or flow_nonce


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
        session_data = _load_connect_session(parsed["session"][0])
        assert session_data["next_url"] == "https://vercel.com/done"

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
        session_data = _load_connect_session(parsed["session"][0])
        assert session_data["next_url"] == ""

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

    @parameterized.expand(
        [
            ("us_cloud", "us.posthog.com", "posthog.com"),
            ("eu_cloud", "eu.posthog.com", "posthog.com"),
            ("self_hosted", "posthog.example.com", ""),
            ("local_dev", "localhost:8000", ""),
        ]
    )
    @override_settings(
        VERCEL_CLIENT_INTEGRATION_ID="client_id",
        VERCEL_CLIENT_INTEGRATION_SECRET="secret",
        SESSION_COOKIE_SECURE=True,
    )
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_callback_binds_session_to_browser_cookie(
        self, _name: str, host: str, expected_domain: str, mock_client_class: MagicMock
    ) -> None:
        self.client.logout()
        _mock_vercel_client(mock_client_class)

        response = self.client.get(self.url, {"code": "good_code"}, HTTP_HOST=host)

        cookie = _flow_cookie(response)
        assert cookie["domain"] == expected_domain
        assert cookie["path"] == "/api/vercel/connect"
        assert cookie["max-age"] == 600
        assert cookie["httponly"] is True
        assert cookie["secure"] is True
        assert cookie["samesite"] == "Lax"


@override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="secret")
class TestVercelConnectSessionInfo(VercelConnectTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/api/vercel/connect/session"

    def test_missing_session_returns_400(self):
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_expired_session_returns_400(self):
        response = self.client.get(self.url, {"session": "bogus-token"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_returns_orgs_where_user_is_admin(self):
        session_token = self._seed_session()

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["next_url"] == "https://vercel.com/done"
        assert len(data["organizations"]) == 1
        assert data["organizations"][0]["name"] == self.organization.name
        assert data["organizations"][0]["already_linked"] is False

    @patch("ee.api.vercel.vercel_connect._is_installation_orphaned", return_value=False)
    def test_marks_already_linked_orgs(self, _mock_orphaned):
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_existing",
            config={"credentials": {"access_token": "tok"}},
            created_by=self.user,
        )
        session_token = self._seed_session()

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["organizations"][0]["already_linked"] is True

    @patch("ee.api.vercel.vercel_connect._is_installation_orphaned", return_value=True)
    def test_orphaned_integration_cleaned_up_in_session(self, _mock_orphaned):
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_orphaned",
            config={"credentials": {"access_token": "tok_dead"}},
            created_by=self.user,
        )
        Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(self.team.pk),
            config={"type": "connectable"},
        )
        session_token = self._seed_session()

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["organizations"][0]["already_linked"] is False
        assert not OrganizationIntegration.objects.filter(integration_id="icfg_orphaned").exists()
        assert not Integration.objects.filter(team=self.team, kind=Integration.IntegrationKind.VERCEL).exists()

    @parameterized.expand(REJECTED_SESSIONS)
    @patch("ee.api.vercel.vercel_connect.capture_exception")
    @patch("ee.api.vercel.vercel_connect._is_installation_orphaned", return_value=True)
    def test_rejects_other_browser_before_cleaning_up_orphans(
        self,
        _name: str,
        token_nonce: str | None,
        cookie_flow_nonce: str | None,
        cookie_value: str | None,
        expected_reason: str,
        _mock_orphaned: MagicMock,
        mock_capture_exception: MagicMock,
    ) -> None:
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_orphaned",
            config={"credentials": {"access_token": "tok_dead"}},
            created_by=self.user,
        )
        session_token = (
            _sign_connect_session(CACHED_SESSION_DATA, browser_nonce=token_nonce)
            if token_nonce
            else encrypt_payload(CACHED_SESSION_DATA, salt=CONNECT_SALT, jti=True)
        )
        self._set_nonce_cookie(cookie_flow_nonce, cookie_value)

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Session expired or invalid" in response.json()["detail"]
        assert OrganizationIntegration.objects.filter(integration_id="icfg_orphaned").exists()
        assert mock_capture_exception.call_args.args[1]["reason"] == expected_reason

    def test_excludes_orgs_where_user_is_member_not_admin(self):
        other_org = Organization.objects.create(name="Other Org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=other_org,
            level=OrganizationMembership.Level.MEMBER,
        )
        session_token = self._seed_session()

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code == status.HTTP_200_OK
        org_names = [o["name"] for o in response.json()["organizations"]]
        assert "Other Org" not in org_names

    def test_unauthenticated_returns_403(self):
        self.client.logout()
        session_token = self._seed_session()

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="secret")
class TestVercelConnectComplete(VercelConnectTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/api/vercel/connect/complete"

    def test_expired_session_returns_400(self):
        response = self.client.post(
            self.url,
            {
                "session": "bogus-token",
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_successful_link_creates_integration_and_resource(self, mock_client_class, mock_vercel_integration):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.import_resource.return_value = OperationResult(success=True)
        session_token = self._seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["status"] == "linked"
        assert data["organization_name"] == self.organization.name

        org_integration = OrganizationIntegration.objects.get(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        )
        assert org_integration.config["type"] == "connectable"
        assert org_integration.sensitive_config["credentials"]["access_token"] == "vercel_token_123"
        assert org_integration.integration_id == "icfg_connect_test"

        resource = Integration.objects.get(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
        )
        assert resource.integration_id == str(self.team.pk)
        assert resource.config["type"] == "connectable"

        mock_client.import_resource.assert_called_once()
        call_kwargs = mock_client.import_resource.call_args[1]
        assert call_kwargs["integration_config_id"] == "icfg_connect_test"
        assert call_kwargs["resource_id"] == str(resource.pk)
        assert call_kwargs["product_id"] == "posthog"
        assert call_kwargs["name"] == self.team.name
        mock_vercel_integration.bulk_sync_feature_flags_to_vercel.assert_called_once_with(self.team)

        secrets = call_kwargs["secrets"]
        secrets_by_name = {secret["name"]: secret for secret in secrets}
        assert set(secrets_by_name) == {
            "NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN",
            "NEXT_PUBLIC_POSTHOG_HOST",
            "VITE_POSTHOG_PROJECT_TOKEN",
            "VITE_POSTHOG_HOST",
            "NUXT_PUBLIC_POSTHOG_PROJECT_TOKEN",
            "NUXT_PUBLIC_POSTHOG_HOST",
            "PUBLIC_POSTHOG_PROJECT_TOKEN",
            "PUBLIC_POSTHOG_HOST",
        }
        assert secrets[0]["name"] == "NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN"
        for prefix in EXPECTED_ENV_PREFIXES:
            token_secret = secrets_by_name[f"{prefix}POSTHOG_PROJECT_TOKEN"]
            assert token_secret["value"] == self.team.api_token
            assert "environmentOverrides" not in token_secret

            host_secret = secrets_by_name[f"{prefix}POSTHOG_HOST"]
            assert host_secret["value"].startswith(("https://", "http://"))
            assert "environmentOverrides" not in host_secret

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_link_with_different_environments_sets_overrides_on_every_prefix(
        self, mock_client_class, mock_vercel_integration
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.import_resource.return_value = OperationResult(success=True)

        preview_team = Team.objects.create(
            organization=self.organization, name="Preview Team", api_token="preview_token"
        )
        development_team = Team.objects.create(
            organization=self.organization, name="Development Team", api_token="development_token"
        )
        session_token = self._seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {
                    "production": self.team.pk,
                    "preview": preview_team.pk,
                    "development": development_team.pk,
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED

        call_kwargs = mock_client.import_resource.call_args[1]
        secrets_by_name = {secret["name"]: secret for secret in call_kwargs["secrets"]}

        for prefix in EXPECTED_ENV_PREFIXES:
            token_secret = secrets_by_name[f"{prefix}POSTHOG_PROJECT_TOKEN"]
            assert token_secret["value"] == self.team.api_token
            assert token_secret["environmentOverrides"] == {
                "preview": "preview_token",
                "development": "development_token",
            }

            host_secret = secrets_by_name[f"{prefix}POSTHOG_HOST"]
            assert "environmentOverrides" not in host_secret

    def test_non_member_returns_403(self):
        other_org = Organization.objects.create(name="Not My Org")
        session_token = self._seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(other_org.id),
                "environment_mapping": {"production": self.team.pk},
            },
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
        session_token = self._seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(other_org.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_replay_returns_400(self, mock_client_class, _mock_vercel_integration):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.import_resource.return_value = OperationResult(success=True)
        session_token = self._seed_session()

        self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )
        self._set_nonce_cookie(BROWSER_NONCE)

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already used" in response.json()["detail"]

    @parameterized.expand(REJECTED_BROWSER_COOKIES)
    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_rejected_browser_leaves_session_usable_by_its_own_browser(
        self,
        _name: str,
        browser_nonce: str | None,
        mock_client_class: MagicMock,
        _mock_vercel_integration: MagicMock,
    ) -> None:
        mock_client_class.return_value.import_resource.return_value = OperationResult(success=True)
        session_token = self._seed_session()
        body = {
            "session": session_token,
            "organization_id": str(self.organization.id),
            "environment_mapping": {"production": self.team.pk},
        }

        self._set_nonce_cookie(browser_nonce)
        rejected_response = self.client.post(self.url, body, content_type="application/json")
        self._set_nonce_cookie(BROWSER_NONCE)
        accepted_response = self.client.post(self.url, body, content_type="application/json")

        assert rejected_response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Session expired or invalid" in rejected_response.json()["detail"]
        assert accepted_response.status_code == status.HTTP_201_CREATED

    @patch("ee.api.vercel.vercel_connect._is_installation_orphaned", return_value=False)
    def test_already_linked_org_returns_400(self, _mock_orphaned):
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_existing",
            config={"credentials": {"access_token": "tok_old"}},
            created_by=self.user,
        )
        session_token = self._seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already has a Vercel integration" in response.json()["detail"]
        assert OrganizationIntegration.objects.filter(integration_id="icfg_existing").exists()

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    @patch("ee.api.vercel.vercel_connect._is_installation_orphaned", return_value=True)
    def test_stale_integration_deleted_and_new_one_created(
        self, _mock_orphaned, mock_client_class, _mock_vercel_integration
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.import_resource.return_value = OperationResult(success=True)
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_stale",
            config={"credentials": {"access_token": "tok_stale"}},
            created_by=self.user,
        )
        stale_resource = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(self.team.pk),
            config={"type": "connectable"},
        )
        session_token = self._seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["status"] == "linked"
        assert not OrganizationIntegration.objects.filter(integration_id="icfg_stale").exists()
        new_integration = OrganizationIntegration.objects.get(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        )
        assert new_integration.integration_id == "icfg_connect_test"
        assert not Integration.objects.filter(pk=stale_resource.pk).exists()
        assert Integration.objects.filter(team=self.team, kind=Integration.IntegrationKind.VERCEL).exists()

    def test_unauthenticated_returns_403(self):
        self.client.logout()
        session_token = self._seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_invalid_team_id_returns_400(self):
        session_token = self._seed_session()
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": other_team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not belong to this organization" in response.json()["detail"]
        assert not OrganizationIntegration.objects.filter(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).exists()

    def test_duplicate_team_integration_returns_400(self):
        Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(self.team.pk),
            config={"type": "connectable"},
            created_by=self.user,
        )
        session_token = self._seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already has a Vercel integration" in response.json()["detail"]

    def test_rollback_on_integration_create_failure(self):
        session_token = self._seed_session()
        original_create = Integration.objects.create

        def failing_create(**kwargs):
            if kwargs.get("kind") == Integration.IntegrationKind.VERCEL:
                raise Exception("db error")
            return original_create(**kwargs)

        with patch.object(Integration.objects, "create", side_effect=failing_create):
            response = self.client.post(
                self.url,
                {
                    "session": session_token,
                    "organization_id": str(self.organization.id),
                    "environment_mapping": {"production": self.team.pk},
                },
                content_type="application/json",
            )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert not OrganizationIntegration.objects.filter(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).exists()
        assert not Integration.objects.filter(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
        ).exists()

    @parameterized.expand(
        [
            ("with_status", OperationResult(success=False, error="HTTP error", status_code=403), "HTTP 403"),
            ("without_status", OperationResult(success=False, error="Network error"), "Network error"),
        ]
    )
    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_failed_import_rolls_back_and_returns_400(
        self, _name, import_result, expected_detail, mock_client_class, mock_vercel_integration
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.import_resource.return_value = import_result
        session_token = self._seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_detail in response.json()["detail"]
        assert not OrganizationIntegration.objects.filter(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).exists()
        assert not Integration.objects.filter(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
        ).exists()
        mock_vercel_integration.bulk_sync_feature_flags_to_vercel.assert_not_called()


@override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
class TestVercelConnectEndToEnd(VercelConnectTestBase):
    def setUp(self):
        super().setUp()
        self.callback_url = "/connect/vercel/callback"

    @parameterized.expand(
        [
            ("same_host_signed_in", "testserver", "testserver", True, ""),
            ("us_callback_eu_link_after_login", "us.posthog.com", "eu.posthog.com", False, "posthog.com"),
        ]
    )
    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_end_to_end_callback_to_complete(
        self,
        _name: str,
        callback_host: str,
        link_host: str,
        signed_in_at_callback: bool,
        expected_cookie_domain: str,
        mock_client_class: MagicMock,
        _mock_vercel_integration: MagicMock,
    ) -> None:
        _mock_vercel_client(mock_client_class)
        if not signed_in_at_callback:
            self.client.logout()

        callback_response = self.client.get(self.callback_url, {"code": "good_code"}, HTTP_HOST=callback_host)
        session_token = _session_token_from_redirect(callback_response["Location"])

        self.client.force_login(self.user)
        session_response = self.client.get(
            "/api/vercel/connect/session", {"session": session_token}, HTTP_HOST=link_host
        )
        complete_response = self.client.post(
            "/api/vercel/connect/complete",
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
            HTTP_HOST=link_host,
        )

        assert callback_response.status_code == 302
        assert session_response.status_code == status.HTTP_200_OK
        assert complete_response.status_code == status.HTTP_201_CREATED
        assert complete_response.json()["status"] == "linked"
        cleared_cookie = _flow_cookie(complete_response)
        assert cleared_cookie["max-age"] == 0
        assert cleared_cookie["domain"] == expected_cookie_domain
        assert cleared_cookie["path"] == "/api/vercel/connect"

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_session_from_another_browser_is_rejected(
        self, mock_client_class: MagicMock, _mock_vercel_integration: MagicMock
    ) -> None:
        mock_client = _mock_vercel_client(mock_client_class)
        attacker_browser = Client()

        callback_response = attacker_browser.get(self.callback_url, {"code": "attacker_code"})
        session_token = _session_token_from_redirect(callback_response["Location"])

        session_response = self.client.get("/api/vercel/connect/session", {"session": session_token})
        complete_response = self.client.post(
            "/api/vercel/connect/complete",
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert [session_response.status_code, complete_response.status_code] == [400, 400]
        assert not OrganizationIntegration.objects.filter(organization=self.organization).exists()
        mock_client.import_resource.assert_not_called()

    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_two_link_flows_in_one_browser_both_stay_usable(self, mock_client_class: MagicMock) -> None:
        _mock_vercel_client(mock_client_class)
        session_tokens = [
            _session_token_from_redirect(self.client.get(self.callback_url, {"code": code})["Location"])
            for code in ("first_code", "second_code")
        ]

        responses = [self.client.get("/api/vercel/connect/session", {"session": token}) for token in session_tokens]

        assert [response.status_code for response in responses] == [status.HTTP_200_OK, status.HTTP_200_OK]

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_token_survives_session_flush(self, mock_client_class, _mock_vercel_integration):
        _mock_vercel_client(mock_client_class)

        response = self.client.get(self.callback_url, {"code": "good_code"})
        assert response.status_code == 302
        parsed = parse_qs(urlparse(response["Location"]).query)
        session_token = parsed["session"][0]

        # Simulate SSO login: flush destroys session, then user re-authenticates
        self.client.session.flush()
        self.client.force_login(self.user)

        complete_response = self.client.post(
            "/api/vercel/connect/complete",
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "environment_mapping": {"production": self.team.pk},
            },
            content_type="application/json",
        )

        assert complete_response.status_code == status.HTTP_201_CREATED
        assert complete_response.json()["status"] == "linked"


@override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="secret")
class TestVercelConnectSessionInfoTeams(VercelConnectTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/api/vercel/connect/session"
        self.second_team = Team.objects.create(organization=self.organization, name="Second Team")

    def test_session_info_returns_teams_per_org(self):
        session_token = self._seed_session()

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        org_data = data["organizations"][0]
        assert "teams" in org_data
        team_ids = {t["id"] for t in org_data["teams"]}
        assert self.team.pk in team_ids
        assert self.second_team.pk in team_ids
        for t in org_data["teams"]:
            assert "id" in t
            assert "name" in t
            assert "already_linked" in t

    def test_session_info_marks_already_linked_team(self):
        Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(self.team.pk),
            config={"type": "connectable"},
            created_by=self.user,
        )
        session_token = self._seed_session()

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code == status.HTTP_200_OK
        teams = response.json()["organizations"][0]["teams"]
        team_map = {t["id"]: t for t in teams}
        assert team_map[self.team.pk]["already_linked"] is True
        assert team_map[self.second_team.pk]["already_linked"] is False


class TestSafeVercelSyncSelfHealing(VercelConnectTestBase):
    @patch("ee.vercel.integration.VercelAPIClient")
    @patch("ee.vercel.integration.VercelIntegration._build_secrets", return_value=[{"name": "TOKEN", "value": "tok"}])
    def test_self_healing_creates_missing_integration_resource(self, _mock_secrets, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.import_resource.return_value = OperationResult(success=True)
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_selfheal",
            config={"type": "connectable"},
            sensitive_config={"credentials": {"access_token": "tok_selfheal"}},
            created_by=self.user,
        )
        assert not Integration.objects.filter(team=self.team, kind=Integration.IntegrationKind.VERCEL).exists()

        from ee.vercel.integration import _safe_vercel_sync

        sync_called = MagicMock()
        _safe_vercel_sync("test op", "item_1", self.team, sync_called)

        resource = Integration.objects.get(team=self.team, kind=Integration.IntegrationKind.VERCEL)
        assert resource.integration_id == str(self.team.pk)
        assert resource.config["type"] == "connectable"
        mock_client.import_resource.assert_called_once_with(
            integration_config_id="icfg_selfheal",
            resource_id=str(resource.pk),
            product_id="posthog",
            name=self.team.name,
            secrets=[{"name": "TOKEN", "value": "tok"}],
        )
        sync_called.assert_called_once()

    def test_self_healing_skipped_when_no_installation(self):
        assert not OrganizationIntegration.objects.filter(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).exists()

        from ee.vercel.integration import _safe_vercel_sync

        sync_called = MagicMock()
        _safe_vercel_sync("test op", "item_1", self.team, sync_called)

        assert not Integration.objects.filter(team=self.team, kind=Integration.IntegrationKind.VERCEL).exists()
        sync_called.assert_not_called()


class TestBackfillVercelConnectableResources(VercelConnectTestBase):
    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.vercel.client.VercelAPIClient")
    def test_backfill_creates_missing_resources(self, mock_client_class, mock_vercel_integration):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.import_resource.return_value = OperationResult(success=True)
        mock_vercel_integration._build_secrets.return_value = [{"name": "TOKEN", "value": "tok"}]
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_backfill",
            config={},
            sensitive_config={"credentials": {"access_token": "tok_backfill"}},
            created_by=self.user,
        )
        assert not Integration.objects.filter(team=self.team, kind=Integration.IntegrationKind.VERCEL).exists()

        from ee.api.vercel.tasks import backfill_vercel_connectable_resources

        backfill_vercel_connectable_resources()

        resource = Integration.objects.get(team=self.team, kind=Integration.IntegrationKind.VERCEL)
        assert resource.integration_id == str(self.team.pk)
        mock_client.import_resource.assert_called_once_with(
            integration_config_id="icfg_backfill",
            resource_id=str(resource.pk),
            product_id="posthog",
            name=self.team.name,
            secrets=mock_vercel_integration._build_secrets.return_value,
        )
        mock_vercel_integration.bulk_sync_feature_flags_to_vercel.assert_called_once_with(self.team)

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.vercel.client.VercelAPIClient")
    def test_backfill_skips_teams_with_existing_resources(self, mock_client_class, mock_vercel_integration):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_backfill2",
            config={"credentials": {"access_token": "tok_backfill2"}},
            created_by=self.user,
        )
        Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(self.team.pk),
            config={"type": "connectable"},
            created_by=self.user,
        )

        from ee.api.vercel.tasks import backfill_vercel_connectable_resources

        backfill_vercel_connectable_resources()

        mock_client.import_resource.assert_not_called()
        mock_vercel_integration.bulk_sync_feature_flags_to_vercel.assert_not_called()


class TestDeleteOrphanedIntegration(VercelConnectTestBase):
    @parameterized.expand(
        [
            ("distinct_teams", ["own"], ["other"], {"other"}),
            ("shared_team", ["own"], ["own"], {"own"}),
            ("unmapped_orphan", None, ["other"], {"other"}),
            ("unmapped_sibling", ["own"], None, {"own", "other"}),
        ]
    )
    def test_keeps_only_resources_another_installation_claims(
        self, _name, orphan_teams, sibling_teams, surviving_teams
    ):
        teams = {"own": self.team, "other": Team.objects.create(organization=self.organization, name="Other project")}

        def config(team_keys: list[str] | None) -> dict:
            if team_keys is None:
                return {"type": "connectable"}
            return {"type": "connectable", "environment_mapping": {"production": teams[team_keys[0]].pk}}

        orphaned = OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_orphaned",
            config=config(orphan_teams),
        )
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_live",
            config=config(sibling_teams),
        )
        for team in teams.values():
            Integration.objects.create(
                team=team,
                kind=Integration.IntegrationKind.VERCEL,
                integration_id=str(team.pk),
                config={"type": "connectable"},
            )

        _delete_orphaned_integration(orphaned)

        assert not OrganizationIntegration.objects.filter(pk=orphaned.pk).exists()
        assert OrganizationIntegration.objects.filter(integration_id="icfg_live").exists()
        surviving_team_ids = set(
            Integration.objects.filter(
                team__organization=self.organization, kind=Integration.IntegrationKind.VERCEL
            ).values_list("team_id", flat=True)
        )
        assert surviving_team_ids == {teams[key].pk for key in surviving_teams}


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
