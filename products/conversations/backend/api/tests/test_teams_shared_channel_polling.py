from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.conversations.backend.models import (
    TeamConversationsTeamsChannelSync,
    TeamConversationsTeamsConfig,
    Ticket,
)
from products.conversations.backend.support_teams import (
    GRAPH_REFRESH_SCOPES,
    GRAPH_REFRESH_SCOPES_READONLY,
    refresh_graph_token,
    store_teams_service_url,
)
from products.conversations.backend.tasks import (
    _sync_shared_channel_thread_replies,
    poll_team_shared_channels,
    poll_teams_shared_channels,
)
from products.conversations.backend.teams import (
    graph_message_to_activity,
    graph_reply_to_activity,
    parse_teams_root_message_id,
    post_teams_channel_message_via_graph,
    resolve_shared_channel_team_id,
)

TRUSTED_SERVICE_URL = "https://smba.trafficmanager.net/teams"

CHANNEL_ID = "19:shared-ch@thread.tacv2"
TEAMS_TEAM_ID = "teams-group-1"


def _graph_message(
    *,
    msg_id: str = "m1",
    message_type: str = "message",
    content: str = "<p>hello support</p>",
    user_id: str | None = "aad-user-1",
    deleted: bool = False,
    reply_to_id: str | None = None,
    created_at: str = "2024-01-01T12:00:00Z",
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "id": msg_id,
        "messageType": message_type,
        "createdDateTime": created_at,
        "body": {"contentType": "html", "content": content},
    }
    if deleted:
        msg["deletedDateTime"] = "2024-01-02T00:00:00Z"
    if reply_to_id:
        msg["replyToId"] = reply_to_id
    if user_id is not None:
        msg["from"] = {"user": {"id": user_id, "displayName": "Alice"}}
    else:
        msg["from"] = {"application": {"id": "app-1", "displayName": "SupportHog"}}
    return msg


def _resp(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def _channel_verify_resp() -> MagicMock:
    """Graph GET /teams/{id}/channels/{id} confirming membershipType=shared."""
    return _resp(json_data={"id": CHANNEL_ID, "membershipType": "shared"})


class TestGraphMessageToActivity(BaseTest):
    @parameterized.expand(
        [
            ("normal_message", _graph_message(), True),
            ("deleted_message", _graph_message(deleted=True), False),
            ("system_event", _graph_message(message_type="systemEventMessage"), False),
            ("app_authored", _graph_message(user_id=None), False),
            ("empty_body", _graph_message(content="   "), False),
            ("reply", _graph_message(reply_to_id="root-1"), False),
        ]
    )
    def test_mapping(self, _name: str, msg: dict, should_map: bool) -> None:
        activity = graph_message_to_activity(msg, CHANNEL_ID, "https://smba.trafficmanager.net/teams/")
        if not should_map:
            self.assertIsNone(activity)
            return
        assert activity is not None
        self.assertEqual(activity["id"], "m1")
        self.assertEqual(activity["from"]["aadObjectId"], "aad-user-1")
        self.assertEqual(activity["conversation"]["id"], f"{CHANNEL_ID};messageid=m1")
        self.assertEqual(activity["channelData"]["channel"]["id"], CHANNEL_ID)


class TestGraphReplyToActivity(BaseTest):
    @parameterized.expand(
        [
            ("normal_reply", _graph_message(reply_to_id="root-1"), True),
            ("deleted_reply", _graph_message(reply_to_id="root-1", deleted=True), False),
            ("app_authored", _graph_message(reply_to_id="root-1", user_id=None), False),
            # The /replies endpoint is already scoped to the root thread, so a replyToId
            # that differs from the root (nested quote-reply) is still ingested.
            ("nested_reply_to_id", _graph_message(reply_to_id="other-root"), True),
            ("empty_body", _graph_message(reply_to_id="root-1", content="   "), False),
        ]
    )
    def test_mapping(self, _name: str, msg: dict, should_map: bool) -> None:
        activity = graph_reply_to_activity(msg, CHANNEL_ID, "root-1", TRUSTED_SERVICE_URL)
        if not should_map:
            self.assertIsNone(activity)
            return
        assert activity is not None
        self.assertEqual(activity["id"], msg["id"])
        self.assertEqual(activity["conversation"]["id"], f"{CHANNEL_ID};messageid=root-1")


@patch("products.conversations.backend.tasks._sync_shared_channel_thread_replies")
@patch("products.conversations.backend.teams.requests.post", return_value=_resp(status_code=201))
@patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "Alice", "email": None})
@patch("products.conversations.backend.tasks.get_graph_token", return_value="graph-token")
class TestPollSharedChannel(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {
                    "team_id": TEAMS_TEAM_ID,
                    "team_name": "Group",
                    "channel_id": CHANNEL_ID,
                    "channel_name": "shared",
                    "membership_type": "shared",
                },
            ],
        }
        self.team.save()
        TeamConversationsTeamsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "teams_tenant_id": "tenant-abc",
                "teams_graph_access_token": "graph-tok",
                "teams_graph_refresh_token": "graph-ref",
            },
        )

    def _sync(self) -> TeamConversationsTeamsChannelSync:
        return TeamConversationsTeamsChannelSync.objects.for_team(self.team.id).get(channel_id=CHANNEL_ID)

    @patch("products.conversations.backend.tasks.requests.get")
    def test_first_run_primes_without_creating_tickets(self, mock_get: MagicMock, *_: Any) -> None:
        mock_get.side_effect = [
            _channel_verify_resp(),
            _resp(json_data={"value": [_graph_message()], "@odata.deltaLink": "DELTA1"}),
        ]

        poll_team_shared_channels(self.team.id)

        self.assertEqual(Ticket.objects.filter(team=self.team).count(), 0)
        sync = self._sync()
        self.assertTrue(sync.primed)
        self.assertEqual(sync.delta_link, "DELTA1")

    @patch("products.conversations.backend.tasks.requests.get")
    def test_second_run_creates_one_ticket_and_is_idempotent(self, mock_get: MagicMock, *_: Any) -> None:
        # Prime (first call = verify, second = delta).
        mock_get.side_effect = [
            _channel_verify_resp(),
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA1"}),
        ]
        poll_team_shared_channels(self.team.id)
        self.assertEqual(Ticket.objects.filter(team=self.team).count(), 0)

        # New message after priming -> exactly one ticket. No verify on second run.
        mock_get.side_effect = None
        mock_get.return_value = _resp(json_data={"value": [_graph_message(msg_id="m2")], "@odata.deltaLink": "DELTA2"})
        poll_team_shared_channels(self.team.id)
        self.assertEqual(Ticket.objects.filter(team=self.team).count(), 1)
        self.assertEqual(self._sync().delta_link, "DELTA2")

        # Same message re-delivered -> no duplicate ticket.
        mock_get.return_value = _resp(json_data={"value": [_graph_message(msg_id="m2")], "@odata.deltaLink": "DELTA3"})
        poll_team_shared_channels(self.team.id)
        self.assertEqual(Ticket.objects.filter(team=self.team).count(), 1)

    @patch("products.conversations.backend.tasks.requests.get")
    def test_polled_ticket_uses_service_url_from_config(self, mock_get: MagicMock, *_: Any) -> None:
        TeamConversationsTeamsConfig.objects.filter(team=self.team).update(teams_service_url=TRUSTED_SERVICE_URL)
        mock_get.side_effect = [
            _channel_verify_resp(),
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA1"}),
        ]
        poll_team_shared_channels(self.team.id)

        mock_get.side_effect = None
        mock_get.return_value = _resp(json_data={"value": [_graph_message(msg_id="m2")], "@odata.deltaLink": "DELTA2"})
        poll_team_shared_channels(self.team.id)

        ticket = Ticket.objects.filter(team=self.team).get()
        self.assertEqual(ticket.teams_service_url, TRUSTED_SERVICE_URL)

    @patch("products.conversations.backend.tasks.requests.get")
    def test_pagination_follows_next_link(self, mock_get: MagicMock, *_: Any) -> None:
        # Prime first (verify + delta).
        mock_get.side_effect = [
            _channel_verify_resp(),
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA1"}),
        ]
        poll_team_shared_channels(self.team.id)

        mock_get.side_effect = [
            _resp(json_data={"value": [_graph_message(msg_id="p1")], "@odata.nextLink": "NEXT1"}),
            _resp(json_data={"value": [_graph_message(msg_id="p2")], "@odata.deltaLink": "DELTA_FINAL"}),
        ]
        poll_team_shared_channels(self.team.id)

        self.assertEqual(Ticket.objects.filter(team=self.team).count(), 2)
        self.assertEqual(self._sync().delta_link, "DELTA_FINAL")

    @patch("products.conversations.backend.tasks.requests.get")
    def test_410_resets_state_for_reprime(self, mock_get: MagicMock, *_: Any) -> None:
        mock_get.side_effect = [
            _channel_verify_resp(),
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA1"}),
        ]
        poll_team_shared_channels(self.team.id)
        self.assertTrue(self._sync().primed)

        mock_get.side_effect = None
        mock_get.return_value = _resp(status_code=410)
        poll_team_shared_channels(self.team.id)

        sync = self._sync()
        self.assertFalse(sync.primed)
        self.assertIsNone(sync.delta_link)

    @parameterized.expand([("payment", 402), ("forbidden", 403), ("throttled", 429)])
    @patch("products.conversations.backend.tasks.requests.get")
    def test_error_statuses_skip_without_crashing(
        self, _name: str, status_code: int, mock_get: MagicMock, *_: Any
    ) -> None:
        mock_get.side_effect = [
            _channel_verify_resp(),
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA1"}),
        ]
        poll_team_shared_channels(self.team.id)

        mock_get.side_effect = None
        mock_get.return_value = _resp(status_code=status_code)
        # Should not raise.
        poll_team_shared_channels(self.team.id)
        self.assertEqual(Ticket.objects.filter(team=self.team).count(), 0)

    @patch("products.conversations.backend.tasks.requests.get")
    def test_unknown_future_value_passes_verification(self, mock_get: MagicMock, *_: Any) -> None:
        # Graph reports shared channels as "unknownFutureValue" in some tenants — must still poll.
        mock_get.side_effect = [
            _resp(json_data={"id": CHANNEL_ID, "membershipType": "unknownFutureValue"}),
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA1"}),
        ]
        poll_team_shared_channels(self.team.id)
        self.assertTrue(self._sync().primed)

    @parameterized.expand([("standard", "standard"), ("private", "private")])
    @patch("products.conversations.backend.tasks.requests.get")
    def test_non_shared_channel_is_rejected_and_sync_deleted(
        self, _name: str, membership_type: str, mock_get: MagicMock, *_: Any
    ) -> None:
        mock_get.return_value = _resp(json_data={"id": CHANNEL_ID, "membershipType": membership_type})
        poll_team_shared_channels(self.team.id)

        self.assertFalse(
            TeamConversationsTeamsChannelSync.objects.for_team(self.team.id).filter(channel_id=CHANNEL_ID).exists()
        )

    @patch("products.conversations.backend.tasks.requests.get")
    def test_confirmation_card_posted_via_graph_for_polled_ticket(
        self, mock_get: MagicMock, _token: MagicMock, _resolve: MagicMock, mock_post: MagicMock, *_: Any
    ) -> None:
        mock_get.side_effect = [
            _channel_verify_resp(),
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA1"}),
        ]
        poll_team_shared_channels(self.team.id)
        mock_post.reset_mock()

        mock_get.side_effect = None
        mock_get.return_value = _resp(json_data={"value": [_graph_message(msg_id="m2")], "@odata.deltaLink": "DELTA2"})
        poll_team_shared_channels(self.team.id)

        self.assertEqual(Ticket.objects.filter(team=self.team).count(), 1)
        mock_post.assert_called_once()
        url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs["url"]
        self.assertIn(f"/teams/{TEAMS_TEAM_ID}/channels/{CHANNEL_ID}/messages/m2/replies", url)


@patch("products.conversations.backend.teams.requests.post", return_value=_resp(status_code=201))
@patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "Alice", "email": None})
@patch("products.conversations.backend.tasks.get_graph_token", return_value="graph-token")
class TestPollSharedChannelThreadReplies(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {
                    "team_id": TEAMS_TEAM_ID,
                    "team_name": "Group",
                    "channel_id": CHANNEL_ID,
                    "channel_name": "shared",
                    "membership_type": "shared",
                },
            ],
        }
        self.team.save()
        TeamConversationsTeamsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "teams_tenant_id": "tenant-abc",
                "teams_graph_access_token": "graph-tok",
                "teams_graph_refresh_token": "graph-ref",
            },
        )

    @patch("products.conversations.backend.tasks.requests.get")
    def test_thread_reply_ingested_from_graph_replies(self, mock_get: MagicMock, *_: Any) -> None:
        from datetime import UTC, datetime

        mock_get.side_effect = [
            _channel_verify_resp(),
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA1"}),
        ]
        poll_team_shared_channels(self.team.id)

        mock_get.side_effect = [
            _resp(json_data={"value": [_graph_message(msg_id="root-1")], "@odata.deltaLink": "DELTA2"}),
            _resp(json_data={"value": []}),
        ]
        poll_team_shared_channels(self.team.id)

        ticket = Ticket.objects.filter(team=self.team).get()
        self.assertEqual(ticket.teams_conversation_id, f"{CHANNEL_ID};messageid=root-1")
        ticket.teams_thread_replies_synced_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        ticket.save(update_fields=["teams_thread_replies_synced_at"])

        mock_get.side_effect = [
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA3"}),
            _resp(
                json_data={
                    "value": [
                        _graph_message(
                            msg_id="reply-1",
                            reply_to_id="root-1",
                            content="<p>follow up question</p>",
                            created_at="2024-06-01T12:00:00Z",
                        )
                    ]
                }
            ),
        ]
        poll_team_shared_channels(self.team.id)

        from posthog.models.comment import Comment

        self.assertEqual(Comment.objects.filter(team=self.team, item_id=str(ticket.id)).count(), 2)
        reply_comment = Comment.objects.filter(team=self.team, item_id=str(ticket.id)).order_by("created_at").last()
        assert isinstance(reply_comment.item_context, dict)
        self.assertEqual(reply_comment.item_context.get("teams_graph_message_id"), "reply-1")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.teams_thread_replies_synced_at)

    def _prime_and_create_root_ticket(self, mock_get: MagicMock) -> Ticket:
        """Prime the channel, create a single root-message ticket, and reset its
        reply watermark to a fixed early time (the empty post-creation sweep otherwise
        stamps it with ``now()``, which would skip fixed-timestamp test replies)."""
        from datetime import UTC, datetime

        mock_get.side_effect = [
            _channel_verify_resp(),
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA1"}),
        ]
        poll_team_shared_channels(self.team.id)

        mock_get.side_effect = [
            _resp(json_data={"value": [_graph_message(msg_id="root-1")], "@odata.deltaLink": "DELTA2"}),
            _resp(json_data={"value": []}),
        ]
        poll_team_shared_channels(self.team.id)
        ticket = Ticket.objects.filter(team=self.team).get()
        ticket.teams_thread_replies_synced_at = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        ticket.save(update_fields=["teams_thread_replies_synced_at"])
        return ticket

    @patch("products.conversations.backend.tasks.requests.get")
    def test_reply_with_mismatched_reply_to_id_is_ingested(self, mock_get: MagicMock, *_: Any) -> None:
        from posthog.models.comment import Comment

        ticket = self._prime_and_create_root_ticket(mock_get)

        mock_get.side_effect = [
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA3"}),
            _resp(
                json_data={
                    "value": [
                        _graph_message(
                            msg_id="reply-nested",
                            reply_to_id="some-other-message",
                            content="<p>nested quote reply</p>",
                            created_at="2024-06-01T12:00:00Z",
                        )
                    ]
                }
            ),
        ]
        poll_team_shared_channels(self.team.id)

        self.assertEqual(Comment.objects.filter(team=self.team, item_id=str(ticket.id)).count(), 2)

    @patch("products.conversations.backend.tasks.requests.get")
    def test_reply_within_watermark_lookback_is_ingested(self, mock_get: MagicMock, *_: Any) -> None:
        from datetime import UTC, datetime

        from posthog.models.comment import Comment

        ticket = self._prime_and_create_root_ticket(mock_get)
        # Watermark slightly ahead of the reply's createdDateTime: without the lookback
        # buffer the reply would be skipped as "already synced".
        ticket.teams_thread_replies_synced_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        ticket.save(update_fields=["teams_thread_replies_synced_at"])

        mock_get.side_effect = [
            _resp(json_data={"value": [], "@odata.deltaLink": "DELTA3"}),
            _resp(
                json_data={
                    "value": [
                        _graph_message(
                            msg_id="reply-skew",
                            reply_to_id="root-1",
                            content="<p>arrived a touch before the watermark</p>",
                            created_at="2024-06-01T11:58:00Z",
                        )
                    ]
                }
            ),
        ]
        poll_team_shared_channels(self.team.id)

        self.assertEqual(Comment.objects.filter(team=self.team, item_id=str(ticket.id)).count(), 2)

    @patch("products.conversations.backend.tasks.requests.get")
    def test_reply_dedupe_holds_across_runs(self, mock_get: MagicMock, *_: Any) -> None:
        from posthog.models.comment import Comment

        ticket = self._prime_and_create_root_ticket(mock_get)

        reply_page = {
            "value": [
                _graph_message(
                    msg_id="reply-dupe",
                    reply_to_id="root-1",
                    content="<p>same reply twice</p>",
                    created_at="2024-06-01T12:00:00Z",
                )
            ]
        }
        for delta in ("DELTA3", "DELTA4"):
            mock_get.side_effect = [
                _resp(json_data={"value": [], "@odata.deltaLink": delta}),
                _resp(json_data=reply_page),
            ]
            poll_team_shared_channels(self.team.id)

        self.assertEqual(Comment.objects.filter(team=self.team, item_id=str(ticket.id)).count(), 2)

    @patch("products.conversations.backend.tasks.TEAMS_REPLIES_MAX_TICKETS_PER_CHANNEL", 0)
    @patch("products.conversations.backend.tasks.requests.get")
    def test_delta_surfaced_ticket_synced_outside_round_robin(self, mock_get: MagicMock, *_: Any) -> None:
        from posthog.models.comment import Comment

        ticket = self._prime_and_create_root_ticket(mock_get)
        conversation_id = ticket.teams_conversation_id
        assert conversation_id is not None

        reply_page = _resp(
            json_data={
                "value": [
                    _graph_message(
                        msg_id="reply-delta",
                        reply_to_id="root-1",
                        content="<p>surfaced by delta</p>",
                        created_at="2024-06-01T12:00:00Z",
                    )
                ]
            }
        )

        # Round-robin selection is empty (max=0): without the surfaced id nothing syncs.
        mock_get.side_effect = None
        mock_get.return_value = reply_page
        _sync_shared_channel_thread_replies(
            team=self.team,
            tenant_id="tenant-abc",
            token="graph-token",
            teams_team_id=TEAMS_TEAM_ID,
            channel_id=CHANNEL_ID,
            service_url=TRUSTED_SERVICE_URL,
        )
        self.assertEqual(Comment.objects.filter(team=self.team, item_id=str(ticket.id)).count(), 1)

        # Passing the surfaced conversation id pulls the reply despite the empty window.
        _sync_shared_channel_thread_replies(
            team=self.team,
            tenant_id="tenant-abc",
            token="graph-token",
            teams_team_id=TEAMS_TEAM_ID,
            channel_id=CHANNEL_ID,
            service_url=TRUSTED_SERVICE_URL,
            surfaced_conversation_ids={conversation_id},
        )
        self.assertEqual(Comment.objects.filter(team=self.team, item_id=str(ticket.id)).count(), 2)


class TestStoreTeamsServiceUrl(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.config, _ = TeamConversationsTeamsConfig.objects.update_or_create(
            team=self.team, defaults={"teams_tenant_id": "tenant-abc", "teams_service_url": None}
        )

    @patch("products.conversations.backend.support_teams.is_trusted_teams_service_url", return_value=True)
    def test_persists_trusted_url_and_strips_trailing_slash(self, _trusted: MagicMock) -> None:
        store_teams_service_url("tenant-abc", TRUSTED_SERVICE_URL + "/")
        self.config.refresh_from_db()
        self.assertEqual(self.config.teams_service_url, TRUSTED_SERVICE_URL)

    @patch("products.conversations.backend.support_teams.is_trusted_teams_service_url", return_value=False)
    def test_skips_untrusted_url(self, _trusted: MagicMock) -> None:
        store_teams_service_url("tenant-abc", "https://evil.example.com")
        self.config.refresh_from_db()
        self.assertIsNone(self.config.teams_service_url)

    @patch("products.conversations.backend.support_teams.is_trusted_teams_service_url", return_value=True)
    def test_noop_for_unknown_tenant(self, _trusted: MagicMock) -> None:
        store_teams_service_url("tenant-zzz", TRUSTED_SERVICE_URL)
        self.config.refresh_from_db()
        self.assertIsNone(self.config.teams_service_url)


@patch("products.conversations.backend.support_teams.get_teams_instance_settings")
@patch("products.conversations.backend.support_teams.requests.post")
class TestRefreshGraphTokenScopeFallback(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.config, _ = TeamConversationsTeamsConfig.objects.update_or_create(
            team=self.team,
            defaults={"teams_tenant_id": "tenant-abc", "teams_graph_refresh_token": "ref-1"},
        )

    def _ok(self) -> MagicMock:
        return _resp(json_data={"access_token": "fresh", "refresh_token": "ref-2", "expires_in": 3600})

    def test_falls_back_to_readonly_scopes_when_send_not_consented(
        self, mock_post: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.return_value = {"SUPPORT_TEAMS_APP_ID": "app", "SUPPORT_TEAMS_APP_SECRET": "secret"}
        # First (full scopes) rejected as if Send isn't consented; readonly retry succeeds.
        mock_post.side_effect = [_resp(status_code=400), self._ok()]

        token = refresh_graph_token(self.config)

        self.assertEqual(token, "fresh")
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_post.call_args_list[0].kwargs["data"]["scope"], GRAPH_REFRESH_SCOPES)
        self.assertEqual(mock_post.call_args_list[1].kwargs["data"]["scope"], GRAPH_REFRESH_SCOPES_READONLY)

    def test_no_fallback_when_full_scopes_succeed(self, mock_post: MagicMock, mock_settings: MagicMock) -> None:
        mock_settings.return_value = {"SUPPORT_TEAMS_APP_ID": "app", "SUPPORT_TEAMS_APP_SECRET": "secret"}
        mock_post.return_value = self._ok()

        token = refresh_graph_token(self.config)

        self.assertEqual(token, "fresh")
        self.assertEqual(mock_post.call_count, 1)

    def test_no_readonly_downgrade_on_transient_error(self, mock_post: MagicMock, mock_settings: MagicMock) -> None:
        mock_settings.return_value = {"SUPPORT_TEAMS_APP_ID": "app", "SUPPORT_TEAMS_APP_SECRET": "secret"}
        # Transient failures (429/5xx) must NOT retry read-only — that would downgrade
        # a recoverable full-scope token. Only 400 (consent denied) falls back.
        for status_code in (429, 503):
            mock_post.reset_mock()
            mock_post.return_value = _resp(status_code=status_code)

            with self.assertRaises(ValueError):
                refresh_graph_token(self.config)

            self.assertEqual(mock_post.call_count, 1)
            self.assertEqual(mock_post.call_args_list[0].kwargs["data"]["scope"], GRAPH_REFRESH_SCOPES)


class TestSharedChannelGraphSend(BaseTest):
    @parameterized.expand(
        [
            ("no_marker", "19:plain@thread.tacv2", None),
            ("with_marker", f"{CHANNEL_ID};messageid=root-9", "root-9"),
            ("empty_id", f"{CHANNEL_ID};messageid=", None),
            ("none", None, None),
        ]
    )
    def test_parse_root_message_id(self, _name: str, conversation_id: str | None, expected: str | None) -> None:
        self.assertEqual(parse_teams_root_message_id(conversation_id), expected)

    @parameterized.expand(
        [
            ("shared", "shared", TEAMS_TEAM_ID),
            ("unknown_future_value", "unknownFutureValue", TEAMS_TEAM_ID),
            ("standard", "standard", None),
            ("private", "private", None),
        ]
    )
    def test_resolve_shared_channel_team_id(self, _name: str, membership_type: str, expected: str | None) -> None:
        self.team.conversations_settings = {
            "teams_channels": [
                {"channel_id": CHANNEL_ID, "team_id": TEAMS_TEAM_ID, "membership_type": membership_type}
            ],
        }
        self.assertEqual(resolve_shared_channel_team_id(self.team, CHANNEL_ID), expected)

    def test_resolve_returns_none_for_unconfigured_channel(self) -> None:
        self.team.conversations_settings = {"teams_channels": []}
        self.assertIsNone(resolve_shared_channel_team_id(self.team, CHANNEL_ID))

    @patch("products.conversations.backend.teams.requests.post", return_value=_resp(status_code=201))
    def test_graph_send_posts_reply_to_thread(self, mock_post: MagicMock) -> None:
        status, _message_id = post_teams_channel_message_via_graph(
            team=self.team,
            teams_team_id=TEAMS_TEAM_ID,
            channel_id=CHANNEL_ID,
            html="<p>reply</p>",
            reply_to_message_id="root-1",
            token="tok",
        )
        self.assertEqual(status, 201)
        url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs["url"]
        self.assertIn(f"/teams/{TEAMS_TEAM_ID}/channels/{CHANNEL_ID}/messages/root-1/replies", url)

    @patch("products.conversations.backend.teams.requests.post", return_value=_resp(status_code=403))
    def test_graph_send_returns_status_on_error(self, _mock_post: MagicMock) -> None:
        status, message_id = post_teams_channel_message_via_graph(
            team=self.team,
            teams_team_id=TEAMS_TEAM_ID,
            channel_id=CHANNEL_ID,
            html="<p>reply</p>",
            token="tok",
        )
        self.assertEqual(status, 403)
        self.assertIsNone(message_id)


class TestPollFanout(BaseTest):
    # Graph returns "unknownFutureValue" for shared channels in some tenants, so both
    # it and the literal "shared" must fan out; standard/private must not.
    @parameterized.expand(
        [
            ("shared", "shared", True),
            ("unknown_future_value", "unknownFutureValue", True),
            ("standard", "standard", False),
            ("private", "private", False),
        ]
    )
    @patch("products.conversations.backend.tasks.poll_team_shared_channels.delay")
    def test_fanout_by_membership_type(
        self, _name: str, membership_type: str, should_fan_out: bool, mock_delay: MagicMock
    ) -> None:
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {"channel_id": CHANNEL_ID, "team_id": TEAMS_TEAM_ID, "membership_type": membership_type}
            ],
        }
        self.team.save()
        TeamConversationsTeamsConfig.objects.update_or_create(
            team=self.team,
            defaults={"teams_tenant_id": "tenant-abc", "teams_graph_access_token": "graph-tok"},
        )

        poll_teams_shared_channels()

        if should_fan_out:
            mock_delay.assert_called_once_with(self.team.id)
        else:
            mock_delay.assert_not_called()
