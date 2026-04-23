import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from rest_framework.test import APIClient

from posthog.models.organization import OrganizationMembership

from products.conversations.backend.models import TeamConversationsTeamsConfig


def _make_activity(
    *,
    activity_type: str = "message",
    channel_id: str = "19:ch@thread.tacv2",
    tenant_id: str = "tenant-abc",
    text: str = "Hello",
) -> dict[str, Any]:
    return {
        "type": activity_type,
        "id": "act-123",
        "text": text,
        "serviceUrl": "https://smba.trafficmanager.net/teams/",
        "from": {"id": "29:user", "aadObjectId": "aad-user-1", "role": "user"},
        "conversation": {"id": "19:conv@thread.tacv2"},
        "channelData": {
            "channel": {"id": channel_id},
            "tenant": {"id": tenant_id},
        },
    }


class TestTeamsEventHandler(BaseTest):
    client: APIClient

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"teams_enabled": True}
        self.team.save()
        TeamConversationsTeamsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "teams_tenant_id": "tenant-abc",
                "teams_graph_access_token": "graph-tok",
            },
        )
        self.client = APIClient()
        cache.clear()

    def _post(self, payload: dict[str, Any], **kwargs):
        return self.client.post(
            "/api/conversations/v1/teams/events",
            data=json.dumps(payload),
            content_type="application/json",
            **kwargs,
        )

    @patch("products.conversations.backend.api.teams_events.validate_teams_request")
    def test_invalid_jwt_returns_403(self, mock_validate: MagicMock):
        mock_validate.side_effect = ValueError("JWT validation failed")

        response = self._post(_make_activity())

        assert response.status_code == 403

    @patch("products.conversations.backend.api.teams_events.process_teams_event")
    @patch("products.conversations.backend.api.teams_events.validate_teams_request")
    def test_message_activity_returns_202(self, mock_validate, mock_process):
        mock_validate.return_value = {}

        response = self._post(_make_activity())

        assert response.status_code == 202

    @patch("products.conversations.backend.api.teams_events.validate_teams_request")
    def test_non_message_activity_returns_200(self, mock_validate):
        mock_validate.return_value = {}

        response = self._post(_make_activity(activity_type="conversationUpdate"))

        assert response.status_code == 200

    @patch("products.conversations.backend.api.teams_events.validate_teams_request")
    def test_get_method_returns_405(self, mock_validate):
        response = self.client.get("/api/conversations/v1/teams/events")
        assert response.status_code == 405

    @patch("products.conversations.backend.api.teams_events.validate_teams_request")
    def test_invalid_json_returns_400(self, mock_validate):
        mock_validate.return_value = {}

        response = self.client.post(
            "/api/conversations/v1/teams/events",
            data="{bad",
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("products.conversations.backend.api.teams_events.process_teams_event")
    @patch("products.conversations.backend.api.teams_events.validate_teams_request")
    def test_message_dispatches_celery_task(self, mock_validate, mock_process):
        mock_validate.return_value = {}

        self._post(_make_activity(tenant_id="tenant-abc"))

        mock_process.delay.assert_called_once()
        call_kwargs = mock_process.delay.call_args.kwargs
        assert call_kwargs["tenant_id"] == "tenant-abc"
        assert call_kwargs["activity"]["type"] == "message"

    @patch("products.conversations.backend.api.teams_events.process_teams_event")
    @patch("products.conversations.backend.api.teams_events.validate_teams_request")
    def test_unknown_tenant_proxies_or_warns(self, mock_validate, mock_process):
        mock_validate.return_value = {}

        self._post(_make_activity(tenant_id="unknown-tenant"))

        mock_process.delay.assert_not_called()


class TestTeamsChannelsEndpoints(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"teams_enabled": True}
        self.team.save()
        TeamConversationsTeamsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "teams_tenant_id": "tenant-abc",
                "teams_graph_access_token": "graph-tok",
                "teams_graph_refresh_token": "graph-ref",
            },
        )

    @patch("products.conversations.backend.api.teams_channels.requests.get")
    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_list_teams_returns_teams(self, _mock_refresh, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "value": [
                {"id": "team-1", "displayName": "Engineering"},
                {"id": "team-2", "displayName": "Support"},
            ]
        }
        mock_get.return_value = mock_resp

        response = self.client.post("/api/conversations/v1/teams/teams")

        assert response.status_code == 200
        data = response.json()
        assert len(data["teams"]) == 2
        assert data["teams"][0]["name"] == "Engineering"

    @patch("products.conversations.backend.api.teams_channels.requests.get")
    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_list_channels_returns_channels(self, _mock_refresh, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "value": [
                {"id": "ch-1", "displayName": "General"},
                {"id": "ch-2", "displayName": "Support"},
            ]
        }
        mock_get.return_value = mock_resp

        response = self.client.post(
            "/api/conversations/v1/teams/channels",
            data=json.dumps({"team_id": "00000000-0000-0000-0000-000000000001"}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["channels"]) == 2
        assert data["channels"][1]["name"] == "Support"

    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_list_channels_requires_team_id(self, _mock_refresh):
        response = self.client.post(
            "/api/conversations/v1/teams/channels",
            data=json.dumps({}),
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("products.conversations.backend.api.teams_channels.requests.get")
    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_list_teams_graph_failure_returns_502(self, _mock_refresh, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_get.return_value = mock_resp

        response = self.client.post("/api/conversations/v1/teams/teams")

        assert response.status_code == 502

    def test_list_teams_requires_auth(self):
        self.client.logout()
        response = self.client.post("/api/conversations/v1/teams/teams")
        assert response.status_code in (401, 403)

    def test_list_channels_requires_auth(self):
        self.client.logout()
        response = self.client.post(
            "/api/conversations/v1/teams/channels",
            data=json.dumps({"team_id": "x"}),
            content_type="application/json",
        )
        assert response.status_code in (401, 403)


class TestTeamsOAuthEndpoints(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.team.conversations_enabled = True
        self.team.save()

    @patch("products.conversations.backend.api.teams_oauth.get_instance_settings")
    def test_authorize_returns_oauth_url(self, mock_settings):
        mock_settings.return_value = {"SUPPORT_TEAMS_APP_ID": "app-id-123"}

        response = self.client.get("/api/conversations/v1/teams/authorize")

        assert response.status_code == 200
        data = response.json()
        assert "url" in data
        parsed = urlparse(data["url"])
        assert parsed.scheme == "https"
        assert parsed.hostname == "login.microsoftonline.com"
        qs = parse_qs(parsed.query)
        assert qs["client_id"] == ["app-id-123"]
        assert "offline_access" in qs.get("scope", [""])[0]

    @patch("products.conversations.backend.api.teams_oauth.get_instance_settings")
    def test_authorize_not_configured_returns_503(self, mock_settings):
        mock_settings.return_value = {"SUPPORT_TEAMS_APP_ID": ""}

        response = self.client.get("/api/conversations/v1/teams/authorize")

        assert response.status_code == 503

    def test_disconnect_when_not_connected_succeeds(self):
        response = self.client.post("/api/conversations/v1/teams/disconnect")
        assert response.status_code == 200

    def test_disconnect_clears_config(self):
        TeamConversationsTeamsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "teams_tenant_id": "t-1",
                "teams_graph_access_token": "tok",
                "teams_graph_refresh_token": "ref",
            },
        )
        self.team.conversations_settings = {"teams_enabled": True}
        self.team.save()

        response = self.client.post("/api/conversations/v1/teams/disconnect")

        assert response.status_code == 200
        self.team.refresh_from_db()
        assert self.team.conversations_settings.get("teams_enabled") is False

    def test_authorize_requires_auth(self):
        self.client.logout()
        response = self.client.get("/api/conversations/v1/teams/authorize")
        assert response.status_code in (401, 403)

    def test_disconnect_requires_auth(self):
        self.client.logout()
        response = self.client.post("/api/conversations/v1/teams/disconnect")
        assert response.status_code in (401, 403)
