from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team

from ee.api.vercel.vercel_connect import _load_connect_session, _sign_connect_session, _validate_next_url
from ee.vercel.client import OAuthTokenResponse, OperationResult

CACHED_SESSION_DATA = {
    "access_token": "vercel_token_123",
    "token_type": "Bearer",
    "installation_id": "icfg_connect_test",
    "user_id": "vercel_user_1",
    "team_id": "team_vercel_1",
    "configuration_id": "cfg_1",
    "next_url": "https://vercel.com/done",
}


def _seed_session(data: dict | None = None) -> str:
    return _sign_connect_session(data or CACHED_SESSION_DATA)


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
        session_token = _seed_session()

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
        session_token = _seed_session()

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
        session_token = _seed_session()

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["organizations"][0]["already_linked"] is False
        assert not OrganizationIntegration.objects.filter(integration_id="icfg_orphaned").exists()

    def test_excludes_orgs_where_user_is_member_not_admin(self):
        other_org = Organization.objects.create(name="Other Org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=other_org,
            level=OrganizationMembership.Level.MEMBER,
        )
        session_token = _seed_session()

        response = self.client.get(self.url, {"session": session_token})

        assert response.status_code == status.HTTP_200_OK
        org_names = [o["name"] for o in response.json()["organizations"]]
        assert "Other Org" not in org_names

    def test_unauthenticated_returns_403(self):
        self.client.logout()
        session_token = _seed_session()

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
            {"session": "bogus-token", "organization_id": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_successful_link_creates_integration_and_resource(self, mock_client_class, mock_vercel_integration):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.import_resource.return_value = OperationResult(success=True)
        mock_vercel_integration._build_secrets.return_value = [{"name": "TOKEN", "value": "tok"}]
        session_token = _seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "team_id": self.team.pk,
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

        mock_client.import_resource.assert_called_once_with(
            integration_config_id="icfg_connect_test",
            resource_id=str(resource.pk),
            product_id="posthog",
            name=self.team.name,
            secrets=mock_vercel_integration._build_secrets.return_value,
        )
        mock_vercel_integration.bulk_sync_feature_flags_to_vercel.assert_called_once_with(self.team)

    def test_non_member_returns_403(self):
        other_org = Organization.objects.create(name="Not My Org")
        session_token = _seed_session()

        response = self.client.post(
            self.url,
            {"session": session_token, "organization_id": str(other_org.id), "team_id": self.team.pk},
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
        session_token = _seed_session()

        response = self.client.post(
            self.url,
            {"session": session_token, "organization_id": str(other_org.id), "team_id": self.team.pk},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_replay_returns_400(self, mock_client_class, _mock_vercel_integration):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.import_resource.return_value = OperationResult(success=True)
        session_token = _seed_session()

        self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "team_id": self.team.pk,
            },
            content_type="application/json",
        )

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "team_id": self.team.pk,
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already used" in response.json()["detail"]

    @patch("ee.api.vercel.vercel_connect._is_installation_orphaned", return_value=False)
    def test_already_linked_org_returns_400(self, _mock_orphaned):
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="icfg_existing",
            config={"credentials": {"access_token": "tok_old"}},
            created_by=self.user,
        )
        session_token = _seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "team_id": self.team.pk,
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
        session_token = _seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "team_id": self.team.pk,
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

    def test_unauthenticated_returns_403(self):
        self.client.logout()
        session_token = _seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "team_id": self.team.pk,
            },
            content_type="application/json",
        )

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_invalid_team_id_returns_400(self):
        session_token = _seed_session()
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "team_id": other_team.pk,
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
        session_token = _seed_session()

        response = self.client.post(
            self.url,
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "team_id": self.team.pk,
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already has a Vercel integration" in response.json()["detail"]

    def test_rollback_on_integration_create_failure(self):
        session_token = _seed_session()
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
                    "team_id": self.team.pk,
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


@override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="secret")
class TestVercelConnectEndToEnd(VercelConnectTestBase):
    def setUp(self):
        super().setUp()
        self.callback_url = "/connect/vercel/callback"

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_end_to_end_callback_to_complete(self, mock_client_class, _mock_vercel_integration):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
            access_token="tok_e2e",
            token_type="Bearer",
            installation_id="icfg_e2e",
            user_id="usr_e2e",
            team_id="team_e2e",
        )
        mock_client.import_resource.return_value = OperationResult(success=True)

        response = self.client.get(self.callback_url, {"code": "good_code"})
        assert response.status_code == 302
        parsed = parse_qs(urlparse(response["Location"]).query)
        session_token = parsed["session"][0]

        complete_response = self.client.post(
            "/api/vercel/connect/complete",
            {
                "session": session_token,
                "organization_id": str(self.organization.id),
                "team_id": self.team.pk,
            },
            content_type="application/json",
        )

        assert complete_response.status_code == status.HTTP_201_CREATED
        assert complete_response.json()["status"] == "linked"

    @patch("ee.vercel.integration.VercelIntegration")
    @patch("ee.api.vercel.vercel_connect.VercelAPIClient")
    def test_token_survives_session_flush(self, mock_client_class, _mock_vercel_integration):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.oauth_token_exchange.return_value = OAuthTokenResponse(
            access_token="tok_sso",
            token_type="Bearer",
            installation_id="icfg_sso",
            user_id="usr_sso",
            team_id="team_sso",
        )
        mock_client.import_resource.return_value = OperationResult(success=True)

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
                "team_id": self.team.pk,
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
        session_token = _seed_session()

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
        session_token = _seed_session()

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
