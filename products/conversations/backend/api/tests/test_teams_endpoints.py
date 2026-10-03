import json
import time
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import OperationalError

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models.organization import OrganizationMembership

from products.conversations.backend.models import TeamConversationsTeamsConfig
from products.conversations.backend.support_teams import JWKS_CACHE_KEY

TEAMS_EVENTS_MODULE = "products.conversations.backend.services.teams_events"
SUPPORT_TEAMS_MODULE = "products.conversations.backend.support_teams"
TEAMS_APP_ID = "00000000-0000-0000-0000-000000000009"
BOT_FROM_ID = f"28:{TEAMS_APP_ID}"
JWKS_URI = "https://login.botframework.com/v1/.well-known/keys"
SERVICE_URL = "https://smba.trafficmanager.net/teams/"


def _make_activity(
    *,
    activity_type: str = "message",
    teams_channel_id: str = "19:ch@thread.tacv2",
    tenant_id: str = "tenant-abc",
    text: str = "I have an issue",
) -> dict[str, Any]:
    return {
        "type": activity_type,
        "id": "act-123",
        "channelId": "msteams",
        "text": text,
        "serviceUrl": SERVICE_URL,
        "from": {"id": "29:user", "aadObjectId": "aad-user-1", "role": "user"},
        "conversation": {"id": "19:conv@thread.tacv2"},
        "channelData": {
            "channel": {"id": teams_channel_id},
            "tenant": {"id": tenant_id},
        },
    }


class TestTeamsEventHandler(BaseTest):
    client: APIClient
    private_key: rsa.RSAPrivateKey
    public_key: rsa.RSAPublicKey

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = cls.private_key.public_key()

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
        reset_consumer_registry()
        self.addCleanup(reset_consumer_registry)

        for patcher in (
            patch(
                f"{SUPPORT_TEAMS_MODULE}.get_teams_instance_settings",
                return_value={"SUPPORT_TEAMS_APP_ID": TEAMS_APP_ID},
            ),
            patch(
                "jwt.PyJWKClient.get_signing_key_from_jwt",
                return_value=SimpleNamespace(key=self.public_key, _jwk_data={"endorsements": ["msteams"]}),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # Primed, so the getter serves the signing-key URI without fetching Microsoft's
        # discovery document.
        cache.set(JWKS_CACHE_KEY, JWKS_URI, 3600)

    def _token(self, **claims: Any) -> str:
        payload: dict[str, Any] = {
            "iss": "https://api.botframework.com",
            "aud": TEAMS_APP_ID,
            "serviceurl": SERVICE_URL,
            "tid": "tenant-abc",
            "exp": int(time.time()) + 300,
            **claims,
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def _post_raw(self, body: bytes, token: str | None = None):
        headers = {} if token is None else {"authorization": f"Bearer {token}"}
        return self.client.post(
            "/api/conversations/v1/teams/events",
            data=body,
            content_type="application/json",
            headers=headers,
        )

    def _post(self, payload: dict[str, Any], token: str | None = None):
        return self._post_raw(json.dumps(payload).encode("utf-8"), token=token or self._token())

    def test_a_request_without_a_bot_framework_token_returns_403(self):
        response = self._post_raw(json.dumps(_make_activity()).encode("utf-8"))

        assert response.status_code == 403

    def test_a_token_signed_for_another_bot_returns_403(self):
        response = self._post(_make_activity(), token=self._token(aud="another-app-id"))

        assert response.status_code == 403

    @parameterized.expand(
        [
            # A conversationUpdate that adds somebody other than the bot.
            ("conversation_update", "conversationUpdate"),
            # Bot Framework sends activity types this bot does not act on, and they are receipted.
            ("installation_update", "installationUpdate"),
        ]
    )
    @patch(f"{TEAMS_EVENTS_MODULE}.send_teams_help")
    def test_an_activity_this_bot_does_not_act_on_is_receipted(
        self, _name: str, activity_type: str, mock_help: MagicMock
    ):
        response = self._post(_make_activity(activity_type=activity_type))

        assert response.status_code == 202
        mock_help.delay.assert_not_called()

    @patch(f"{TEAMS_EVENTS_MODULE}.send_teams_help")
    def test_conversation_update_with_bot_added_enqueues_welcome(self, mock_help: MagicMock):
        """Cert 11.4.4.3: bot must send a proactive welcome on install."""
        activity = _make_activity(activity_type="conversationUpdate")
        activity["recipient"] = {"id": BOT_FROM_ID, "name": "SupportHog"}
        activity["membersAdded"] = [{"id": BOT_FROM_ID}]

        response = self._post(activity)

        assert response.status_code == 202
        mock_help.delay.assert_called_once()
        call_kwargs = mock_help.delay.call_args.kwargs
        assert call_kwargs["activity"]["type"] == "conversationUpdate"
        assert call_kwargs["reply"] is False

    @patch(f"{TEAMS_EVENTS_MODULE}.send_teams_help")
    def test_conversation_update_with_other_member_does_not_welcome(self, mock_help: MagicMock):
        """A non-bot member joining must not trigger the welcome card."""
        activity = _make_activity(activity_type="conversationUpdate")
        activity["recipient"] = {"id": BOT_FROM_ID, "name": "SupportHog"}
        activity["membersAdded"] = [{"id": "29:some-other-user"}]

        response = self._post(activity)

        assert response.status_code == 202
        mock_help.delay.assert_not_called()

    @patch(f"{TEAMS_EVENTS_MODULE}.process_teams_event")
    @patch(f"{TEAMS_EVENTS_MODULE}.send_teams_help")
    def test_generic_command_replies_with_help_card_without_oauth(self, mock_help: MagicMock, mock_process: MagicMock):
        """Cert 11.4.4.3: bot must respond to "Hi" / "Hello" / "Help" even
        before OAuth — AppSource validators run against an unconnected tenant."""
        # A tenant we have no PostHog config for, which is the validator's tenant.
        activity = _make_activity(text="Hi", tenant_id="unknown-tenant")

        response = self._post(activity, token=self._token(tid="unknown-tenant"))

        assert response.status_code == 202
        mock_help.delay.assert_called_once()
        assert mock_help.delay.call_args.kwargs["reply"] is True
        # Crucially, do NOT also try to create a ticket.
        mock_process.delay.assert_not_called()

    @patch(f"{TEAMS_EVENTS_MODULE}.process_teams_event")
    @patch(f"{TEAMS_EVENTS_MODULE}.send_teams_help")
    def test_non_command_message_does_not_hit_help_path(self, mock_help: MagicMock, mock_process: MagicMock):
        self._post(_make_activity(text="I have an issue"))

        mock_help.delay.assert_not_called()
        mock_process.delay.assert_called_once()

    @parameterized.expand(
        [
            ("command_message", "message", "Hi"),
            ("bot_added", "conversationUpdate", ""),
        ]
    )
    @patch(f"{TEAMS_EVENTS_MODULE}.send_teams_help")
    def test_a_help_card_is_posted_once_across_bot_framework_retries(
        self, _name: str, activity_type: str, text: str, mock_help: MagicMock
    ):
        """Bot Framework retries on 5xx for ~10 mins with the same activity.id."""
        activity = _make_activity(activity_type=activity_type, text=text)
        if activity_type == "conversationUpdate":
            activity["recipient"] = {"id": BOT_FROM_ID, "name": "SupportHog"}
            activity["membersAdded"] = [{"id": BOT_FROM_ID}]

        first = self._post(activity)
        second = self._post(activity)

        assert first.status_code == 202
        assert second.status_code == 202
        mock_help.delay.assert_called_once()

    @patch(f"{TEAMS_EVENTS_MODULE}.send_teams_help")
    def test_command_message_from_bot_self_id_suppressed(self, mock_help: MagicMock):
        """Defense-in-depth: a spoofed activity claiming from.id == bot must
        not loop us into replying. (Bot Framework doesn't echo, but a valid
        JWT replay shouldn't bypass that.)"""
        activity = _make_activity(text="Hi")
        activity["from"] = {"id": BOT_FROM_ID, "aadObjectId": "aad-bot", "role": "bot"}

        response = self._post(activity)

        assert response.status_code == 202
        mock_help.delay.assert_not_called()

    @patch(f"{TEAMS_EVENTS_MODULE}.process_teams_event")
    def test_a_body_the_token_does_not_back_is_refused(self, mock_process: MagicMock):
        # The gate itself is covered in posthog/ingress/test/test_teams.py. This is the wiring:
        # the endpoint's own provider runs it, so a replayed token cannot redirect the activity.
        activity = {**_make_activity(), "serviceUrl": "https://attacker.example.com/"}

        response = self._post(activity)

        assert response.status_code == 400
        mock_process.delay.assert_not_called()

    @patch(f"{TEAMS_EVENTS_MODULE}.process_teams_event")
    def test_a_signed_service_url_outside_microsoft_is_not_acted_on(self, mock_process: MagicMock):
        # The claim backs the body here, so ingress accepts the activity. The bot's own bearer
        # token goes to this URL, so the consumer still holds it to Microsoft's endpoints.
        service_url = "https://attacker.example.com/"
        activity = {**_make_activity(), "serviceUrl": service_url}

        response = self._post(activity, token=self._token(serviceurl=service_url))

        assert response.status_code == 202
        mock_process.delay.assert_not_called()

    def test_get_method_returns_405(self):
        response = self.client.get("/api/conversations/v1/teams/events")

        assert response.status_code == 405

    def test_invalid_json_returns_400(self):
        response = self._post_raw(b"{bad", token=self._token())

        assert response.status_code == 400

    @patch(f"{TEAMS_EVENTS_MODULE}.process_teams_event")
    def test_message_dispatches_celery_task(self, mock_process: MagicMock):
        response = self._post(_make_activity(tenant_id="tenant-abc"))

        assert response.status_code == 202
        mock_process.delay.assert_called_once()
        call_kwargs = mock_process.delay.call_args.kwargs
        assert call_kwargs["tenant_id"] == "tenant-abc"
        assert call_kwargs["activity"]["type"] == "message"
        assert call_kwargs["activity_id"] == "act-123"

    @patch(f"{TEAMS_EVENTS_MODULE}.process_teams_event")
    def test_a_tenant_this_region_does_not_hold_runs_nothing_here(self, mock_process: MagicMock):
        response = self._post(_make_activity(tenant_id="unknown-tenant"), token=self._token(tid="unknown-tenant"))

        assert response.status_code == 202
        mock_process.delay.assert_not_called()

    @parameterized.expand(
        [
            ("the owning region accepts it", 202, 202),
            # Bot Framework redelivers on a 5xx, so a forward that never landed keeps no receipt.
            ("the owning region is unreachable", 500, 503),
        ]
    )
    @patch(f"{TEAMS_EVENTS_MODULE}.process_teams_event")
    def test_a_tenant_another_region_owns_is_forwarded_from_the_primary(
        self, _name: str, secondary_status: int, expected_status: int, mock_process: MagicMock
    ):
        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.dispatch.forward.requests.request") as mock_forward,
        ):
            mock_forward.return_value = MagicMock(ok=200 <= secondary_status < 300, status_code=secondary_status)
            response = self._post(_make_activity(tenant_id="unknown-tenant"), token=self._token(tid="unknown-tenant"))

        assert response.status_code == expected_status
        mock_forward.assert_called_once()
        mock_process.delay.assert_not_called()

    @patch(f"{TEAMS_EVENTS_MODULE}.process_teams_event")
    def test_a_tenant_lookup_that_does_not_answer_is_redelivered_rather_than_forwarded(self, mock_process: MagicMock):
        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.dispatch.forward.requests.request") as mock_forward,
            patch("posthog.ingress.dispatch.dispatcher.capture_exception"),
            patch(
                f"{TEAMS_EVENTS_MODULE}._tenant_is_connected_here",
                side_effect=OperationalError("canceling statement due to statement timeout"),
            ),
        ):
            response = self._post(_make_activity(tenant_id="tenant-abc"))

        assert response.status_code == 503
        mock_forward.assert_not_called()
        mock_process.delay.assert_not_called()

        # Nothing claimed a dedup mark on the refused delivery, so Bot Framework's retry of the
        # same activity id runs the lookup again instead of being swallowed as a duplicate.
        retry = self._post(_make_activity(tenant_id="tenant-abc"))

        assert retry.status_code == 202
        mock_process.delay.assert_called_once()


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


class TestTeamsSelectChannelMultiChannel(APIBaseTest):
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

    def _mock_graph_responses(self, mock_get, teams_list, channels_list):
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "joinedTeams" in url:
                resp.json.return_value = {"value": teams_list}
            elif "channels" in url:
                resp.json.return_value = {"value": channels_list}
            return resp

        mock_get.side_effect = side_effect

    @patch("products.conversations.backend.api.teams_channels.requests.get")
    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_add_channel_pair_success(self, _mock_refresh, mock_get):
        team_uuid = "00000000-0000-0000-0000-000000000001"
        self._mock_graph_responses(
            mock_get,
            [{"id": team_uuid, "displayName": "Engineering"}],
            [{"id": "ch-1", "displayName": "General"}],
        )

        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "action": "add",
                    "team_id": team_uuid,
                    "channel_id": "ch-1",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["teams_channels"]) == 1
        assert data["teams_channels"][0]["channel_id"] == "ch-1"
        assert data["teams_channels"][0]["team_name"] == "Engineering"
        assert data["teams_channels"][0]["channel_name"] == "General"

        # Verify legacy scalars are also updated
        self.team.refresh_from_db()
        assert self.team.conversations_settings["teams_channel_id"] == "ch-1"
        assert self.team.conversations_settings["teams_team_id"] == team_uuid

    @patch("products.conversations.backend.api.teams_channels.requests.get")
    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_add_multiple_channels_preserves_existing(self, _mock_refresh, mock_get):
        team_uuid = "00000000-0000-0000-0000-000000000001"
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {"team_id": "t-existing", "team_name": "Existing", "channel_id": "ch-existing", "channel_name": "Old"}
            ],
        }
        self.team.save()

        self._mock_graph_responses(
            mock_get,
            [{"id": team_uuid, "displayName": "Engineering"}],
            [{"id": "ch-new", "displayName": "New Channel"}],
        )

        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "action": "add",
                    "team_id": team_uuid,
                    "channel_id": "ch-new",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["teams_channels"]) == 2
        channel_ids = {c["channel_id"] for c in data["teams_channels"]}
        assert channel_ids == {"ch-existing", "ch-new"}

    @patch("products.conversations.backend.api.teams_channels.requests.get")
    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_add_channel_seeds_from_legacy(self, _mock_refresh, mock_get):
        """First add should seed teams_channels from legacy scalar fields."""
        team_uuid = "00000000-0000-0000-0000-000000000001"
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_team_id": "legacy-team",
            "teams_team_name": "Legacy Team",
            "teams_channel_id": "legacy-ch",
            "teams_channel_name": "Legacy Channel",
        }
        self.team.save()

        self._mock_graph_responses(
            mock_get,
            [{"id": team_uuid, "displayName": "New Team"}],
            [{"id": "new-ch", "displayName": "New Channel"}],
        )

        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "action": "add",
                    "team_id": team_uuid,
                    "channel_id": "new-ch",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["teams_channels"]) == 2
        channel_ids = {c["channel_id"] for c in data["teams_channels"]}
        assert channel_ids == {"legacy-ch", "new-ch"}

    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_remove_channel_pair_success(self, _mock_refresh):
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {"team_id": "t1", "team_name": "Team 1", "channel_id": "ch-1", "channel_name": "Ch 1"},
                {"team_id": "t2", "team_name": "Team 2", "channel_id": "ch-2", "channel_name": "Ch 2"},
            ],
        }
        self.team.save()

        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "action": "remove",
                    "channel_id": "ch-1",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["teams_channels"]) == 1
        assert data["teams_channels"][0]["channel_id"] == "ch-2"

        # Legacy scalars should now point to remaining channel
        self.team.refresh_from_db()
        assert self.team.conversations_settings["teams_channel_id"] == "ch-2"

    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_remove_last_channel_clears_legacy(self, _mock_refresh):
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {"team_id": "t1", "team_name": "Team 1", "channel_id": "ch-1", "channel_name": "Ch 1"},
            ],
            "teams_channel_id": "ch-1",
        }
        self.team.save()

        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "action": "remove",
                    "channel_id": "ch-1",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["teams_channels"]) == 0

        self.team.refresh_from_db()
        assert self.team.conversations_settings.get("teams_channel_id") is None
        assert self.team.conversations_settings.get("teams_team_id") is None

    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_remove_nonexistent_channel_returns_404(self, _mock_refresh):
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {"team_id": "t1", "channel_id": "ch-1"},
            ],
        }
        self.team.save()

        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "action": "remove",
                    "channel_id": "ch-nonexistent",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 404

    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_add_without_team_id_returns_400(self, _mock_refresh):
        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "action": "add",
                    "channel_id": "ch-1",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["error"] == "team_id_required"

    @patch("products.conversations.backend.api.teams_channels.requests.get")
    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_add_inaccessible_team_returns_400(self, _mock_refresh, mock_get):
        team_uuid = "00000000-0000-0000-0000-000000000001"
        self._mock_graph_responses(
            mock_get,
            [{"id": "other-team", "displayName": "Other"}],  # Different team
            [],
        )

        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "action": "add",
                    "team_id": team_uuid,
                    "channel_id": "ch-1",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["error"] == "team_not_accessible"

    @patch("products.conversations.backend.api.teams_channels.requests.get")
    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_add_inaccessible_channel_returns_400(self, _mock_refresh, mock_get):
        team_uuid = "00000000-0000-0000-0000-000000000001"
        self._mock_graph_responses(
            mock_get,
            [{"id": team_uuid, "displayName": "Engineering"}],
            [{"id": "other-ch", "displayName": "Other Channel"}],  # Different channel
        )

        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "action": "add",
                    "team_id": team_uuid,
                    "channel_id": "ch-1",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["error"] == "channel_not_accessible"

    @patch("products.conversations.backend.api.teams_channels.requests.get")
    @patch("products.conversations.backend.support_teams.refresh_graph_token", return_value="fresh-token")
    def test_legacy_request_format_still_works(self, _mock_refresh, mock_get):
        """Legacy single team_id/channel_id format should still work."""
        team_uuid = "00000000-0000-0000-0000-000000000001"
        self._mock_graph_responses(
            mock_get,
            [{"id": team_uuid, "displayName": "Engineering"}],
            [{"id": "ch-1", "displayName": "General"}],
        )

        response = self.client.post(
            "/api/conversations/v1/teams/select-channel",
            data=json.dumps(
                {
                    "teams_team_id": team_uuid,
                    "teams_channel_id": "ch-1",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["teams_channel_id"] == "ch-1"
        assert data["teams_team_name"] == "Engineering"

        self.team.refresh_from_db()
        assert len(self.team.conversations_settings.get("teams_channels", [])) == 1
