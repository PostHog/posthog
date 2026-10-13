from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import transaction
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.comment import Comment
from posthog.models.team import Team

from products.conversations.backend.models import (
    ConversationDelivery,
    ConversationDeliveryPart,
    TeamConversationsSlackConfig,
    Ticket,
)
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.models.delivery import DELIVERY_SNAPSHOT_MAX_BYTES
from products.conversations.backend.services.delivery import (
    DELIVERY_MAX_AGE,
    DELIVERY_SNAPSHOT_TTL,
    accept_delivery_part,
    claim_delivery_part,
    cleanup_delivery_snapshots,
    redrive_failed_delivery_part,
)
from products.conversations.backend.tasks.slack import (
    process_slack_delivery_part,
    sweep_delivery_parts,
    wake_delivery_part,
)


class FakeSlackResponse(dict):
    def __init__(self, data: dict, headers: dict | None = None, status_code: int = 200) -> None:
        super().__init__(data)
        self.headers = headers or {}
        self.status_code = status_code


def _slack_api_error(error: str, *, retry_after: str | None = None, status_code: int = 400) -> SlackApiError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return SlackApiError(
        message=error,
        response=FakeSlackResponse({"ok": False, "error": error}, headers=headers, status_code=status_code),
    )


class TestWakeDeliveryPart(SimpleTestCase):
    @patch.object(process_slack_delivery_part, "apply_async")
    def test_wake_does_not_retry_broker_publish(self, mock_apply: MagicMock) -> None:
        row = ConversationDeliveryPart(id=uuid4())
        assert wake_delivery_part(row) is True
        mock_apply.assert_called_once_with(kwargs={"delivery_part_id": str(row.id)}, retry=False)

    @patch.object(process_slack_delivery_part, "apply_async", side_effect=ConnectionError("broker down"))
    def test_wake_returns_false_when_broker_publish_fails(self, mock_apply: MagicMock) -> None:
        row = ConversationDeliveryPart(id=uuid4())
        assert wake_delivery_part(row) is False
        mock_apply.assert_called_once()


class TestSlackDelivery(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        TeamConversationsSlackConfig.objects.update_or_create(
            team=self.team,
            defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-test"},
        )
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id="slack-user",
            channel_source=Channel.SLACK,
            slack_channel_id="C123",
            slack_thread_ts="1700000000.000100",
        )

    def _create_reply(self, content: str = "Support reply") -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=content,
            created_by=self.user,
            item_context={"author_type": "team", "is_private": False},
        )

    def _part(self) -> ConversationDeliveryPart:
        return ConversationDeliveryPart.objects.unscoped().select_related("delivery").get()

    def test_enqueue_failure_rolls_back_the_comment(self) -> None:
        with (
            self.assertRaises(RuntimeError),
            transaction.atomic(),
            patch(
                "products.conversations.backend.signals.enqueue_slack_body_delivery",
                side_effect=RuntimeError("outbox write failed"),
            ),
        ):
            self._create_reply()

        assert not Comment.objects.filter(scope="conversations_ticket", item_id=str(self.ticket.id)).exists()
        assert not ConversationDelivery.objects.unscoped().exists()
        assert not ConversationDeliveryPart.objects.unscoped().exists()

    @patch("products.conversations.backend.tasks.slack.wake_delivery_part")
    def test_sweeper_redrives_when_celery_hint_is_lost(self, mock_wake: MagicMock) -> None:
        comment = self._create_reply()
        part = self._part()
        assert part.status == ConversationDeliveryPart.Status.PENDING
        assert part.delivery.comment_id == comment.id
        mock_wake.assert_not_called()

        sweep_delivery_parts()

        mock_wake.assert_called_once()
        assert str(mock_wake.call_args.args[0].id) == str(part.id)

    def test_expired_lease_fencing_ignores_stale_accept(self) -> None:
        self._create_reply()
        part = self._part()
        first = claim_delivery_part(str(part.id))
        assert first is not None

        ConversationDeliveryPart.objects.unscoped().filter(id=part.id).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1),
            updated_at=timezone.now(),
        )
        second = claim_delivery_part(str(part.id))
        assert second is not None
        assert second.part.fencing_token != first.part.fencing_token
        assert second.expired_reclaim is True

        assert accept_delivery_part(first, provider_message_id="stale.ts") is False
        second.part.refresh_from_db()
        assert second.part.status == ConversationDeliveryPart.Status.PROCESSING
        assert accept_delivery_part(second, provider_message_id="live.ts") is True
        second.part.refresh_from_db()
        assert second.part.status == ConversationDeliveryPart.Status.ACCEPTED
        assert second.part.provider_message_id == "live.ts"

    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_timeout_then_duplicate_provider_response_accepts_once(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
    ) -> None:
        self._create_reply()
        part = self._part()
        client_msg_id = part.client_msg_id
        client = MagicMock()
        client.chat_postMessage.side_effect = [
            TimeoutError("read timed out"),
            {"ok": True, "ts": "1700.1"},
        ]
        mock_get_client.return_value = client

        process_slack_delivery_part(str(part.id))
        part.refresh_from_db()
        assert part.status == ConversationDeliveryPart.Status.PENDING
        assert part.client_msg_id == client_msg_id
        assert part.provider_message_id == ""

        part.due_at = timezone.now()
        part.save(update_fields=["due_at", "updated_at"])
        process_slack_delivery_part(str(part.id))
        part.refresh_from_db()
        assert part.status == ConversationDeliveryPart.Status.ACCEPTED
        assert part.provider_message_id == "1700.1"
        assert part.client_msg_id == client_msg_id
        assert [call.kwargs["client_msg_id"] for call in client.chat_postMessage.call_args_list] == [
            client_msg_id,
            client_msg_id,
        ]

        client.chat_postMessage.reset_mock()
        process_slack_delivery_part(str(part.id))
        assert client.chat_postMessage.call_count == 0

    @parameterized.expand(
        [
            (
                "ratelimited",
                _slack_api_error("ratelimited", retry_after="7", status_code=429),
                ConversationDeliveryPart.Status.PENDING,
                "ratelimited",
                7,
            ),
            (
                "internal_error",
                _slack_api_error("internal_error", status_code=500),
                ConversationDeliveryPart.Status.PENDING,
                "internal_error",
                None,
            ),
            (
                "timeout",
                TimeoutError("read timed out"),
                ConversationDeliveryPart.Status.PENDING,
                "timeout",
                None,
            ),
            (
                "token_revoked",
                _slack_api_error("token_revoked"),
                ConversationDeliveryPart.Status.FAILED,
                "token_revoked",
                None,
            ),
            (
                "channel_not_found",
                _slack_api_error("channel_not_found"),
                ConversationDeliveryPart.Status.FAILED,
                "channel_not_found",
                None,
            ),
            (
                "not_authed",
                _slack_api_error("not_authed"),
                ConversationDeliveryPart.Status.FAILED,
                "not_authed",
                None,
            ),
        ]
    )
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_classifies_slack_post_errors(
        self,
        _name: str,
        exc: BaseException,
        expected_status: str,
        expected_error_code: str,
        retry_after_seconds: int | None,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
    ) -> None:
        with time_machine.travel("2026-09-21 12:00:00", tick=False):
            self._create_reply()
            part = self._part()
            client = MagicMock()
            client.chat_postMessage.side_effect = exc
            mock_get_client.return_value = client
            process_slack_delivery_part(str(part.id))
            part.refresh_from_db()
            assert part.status == expected_status
            assert part.last_error_code == expected_error_code
            if expected_status == ConversationDeliveryPart.Status.PENDING:
                assert part.due_at > timezone.now()
                if retry_after_seconds is not None:
                    assert part.due_at == timezone.now() + timedelta(seconds=retry_after_seconds)
            else:
                assert part.terminal_at is not None
                delivery = ConversationDelivery.objects.unscoped().get(id=part.delivery_id)
                assert delivery.status == ConversationDelivery.Status.FAILED

    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload", return_value=b"img")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_image_failure_does_not_retry_accepted_body(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        _read: MagicMock,
    ) -> None:
        image_id = uuid4()
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Support reply",
            rich_content={
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "image",
                                "attrs": {
                                    "src": f"https://app.posthog.com/uploaded_media/{image_id}",
                                    "alt": "img",
                                },
                            }
                        ],
                    }
                ],
            },
            created_by=self.user,
            item_context={"author_type": "team", "is_private": False},
        )
        client = MagicMock()
        client.chat_postMessage.return_value = {"ok": True, "ts": "1700.1"}
        client.api_call.side_effect = TimeoutError("upload")
        mock_get_client.return_value = client

        body = ConversationDeliveryPart.objects.unscoped().get(part_key="body")
        process_slack_delivery_part(str(body.id))
        body.refresh_from_db()
        assert body.status == ConversationDeliveryPart.Status.ACCEPTED
        assert body.provider_message_id == "1700.1"

        image = ConversationDeliveryPart.objects.unscoped().exclude(part_key="body").get()
        assert image.status == ConversationDeliveryPart.Status.PENDING
        process_slack_delivery_part(str(image.id))
        body.refresh_from_db()
        image.refresh_from_db()
        assert body.status == ConversationDeliveryPart.Status.ACCEPTED
        assert body.provider_message_id == "1700.1"
        assert image.status == ConversationDeliveryPart.Status.PENDING
        assert client.chat_postMessage.call_count == 1

    def test_redrive_failed_part_keeps_client_msg_id(self) -> None:
        self._create_reply()
        part = self._part()
        now = timezone.now()
        ConversationDeliveryPart.objects.unscoped().filter(id=part.id).update(
            status=ConversationDeliveryPart.Status.FAILED,
            terminal_at=now,
            last_error_code="token_revoked",
            attempts=4,
            updated_at=now,
        )
        ConversationDelivery.objects.unscoped().filter(id=part.delivery_id).update(
            status=ConversationDelivery.Status.FAILED,
            terminal_at=now,
            updated_at=now,
        )
        client_msg_id = part.client_msg_id
        wake = MagicMock()

        with patch(
            "products.conversations.backend.services.delivery.transaction.on_commit",
            side_effect=lambda fn: fn(),
        ):
            result = redrive_failed_delivery_part(str(part.id), wake=wake)

        assert result is not None
        result.refresh_from_db()
        assert result.status == ConversationDeliveryPart.Status.PENDING
        assert result.attempts == 0
        assert result.client_msg_id == client_msg_id
        wake.assert_called_once()

    def test_redrive_of_an_old_failure_survives_the_max_age_guard(self) -> None:
        self._create_reply()
        part = self._part()
        long_ago = timezone.now() - DELIVERY_MAX_AGE - timedelta(hours=1)
        ConversationDeliveryPart.objects.unscoped().filter(id=part.id).update(
            status=ConversationDeliveryPart.Status.FAILED,
            terminal_at=long_ago,
            last_error_code="token_revoked",
            attempts=4,
            created_at=long_ago,
        )
        ConversationDelivery.objects.unscoped().filter(id=part.delivery_id).update(
            status=ConversationDelivery.Status.FAILED,
            terminal_at=long_ago,
            created_at=long_ago,
        )

        with patch(
            "products.conversations.backend.services.delivery.transaction.on_commit",
            side_effect=lambda fn: fn(),
        ):
            assert redrive_failed_delivery_part(str(part.id), wake=MagicMock()) is not None

        claim = claim_delivery_part(str(part.id))

        assert claim is not None
        part.refresh_from_db()
        assert part.status == ConversationDeliveryPart.Status.PROCESSING
        assert part.last_error_code != "max_age"

    def test_oversized_snapshot_fails_the_part_and_keeps_the_comment(self) -> None:
        with patch(
            "products.conversations.backend.services.delivery._body_snapshot",
            return_value={"text": "x" * (DELIVERY_SNAPSHOT_MAX_BYTES + 1)},
        ):
            comment = self._create_reply()

        assert Comment.objects.filter(id=comment.id).exists()
        part = self._part()
        assert part.status == ConversationDeliveryPart.Status.FAILED
        assert part.last_error_code == "payload_too_large"
        assert part.payload is None
        delivery = ConversationDelivery.objects.unscoped().get(id=part.delivery_id)
        assert delivery.status == ConversationDelivery.Status.FAILED

    def test_accept_rolls_back_part_when_parent_rollup_fails(self) -> None:
        self._create_reply()
        part = self._part()
        claim = claim_delivery_part(str(part.id))
        assert claim is not None

        with (
            patch(
                "products.conversations.backend.services.delivery._roll_up_delivery",
                side_effect=RuntimeError("rollup failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            accept_delivery_part(claim, provider_message_id="1700.1")

        part.refresh_from_db()
        assert part.status == ConversationDeliveryPart.Status.PROCESSING
        delivery = ConversationDelivery.objects.unscoped().get(id=part.delivery_id)
        assert delivery.status == ConversationDelivery.Status.PENDING

    def test_snapshot_cleanup_keeps_failed_parts_for_redrive(self) -> None:
        self._create_reply("Failed body")
        failed = self._part()
        cutoff = timezone.now() - DELIVERY_SNAPSHOT_TTL - timedelta(minutes=1)
        ConversationDeliveryPart.objects.unscoped().filter(id=failed.id).update(
            status=ConversationDeliveryPart.Status.FAILED,
            terminal_at=cutoff,
            updated_at=cutoff,
        )
        ConversationDelivery.objects.unscoped().filter(id=failed.delivery_id).update(
            status=ConversationDelivery.Status.FAILED,
            terminal_at=cutoff,
            updated_at=cutoff,
        )

        self._create_reply("Accepted body")
        accepted = ConversationDeliveryPart.objects.unscoped().exclude(id=failed.id).get()
        ConversationDeliveryPart.objects.unscoped().filter(id=accepted.id).update(
            status=ConversationDeliveryPart.Status.ACCEPTED,
            terminal_at=cutoff,
            updated_at=cutoff,
        )
        ConversationDelivery.objects.unscoped().filter(id=accepted.delivery_id).update(
            status=ConversationDelivery.Status.ACCEPTED,
            terminal_at=cutoff,
            updated_at=cutoff,
        )

        cleanup_delivery_snapshots(timezone.now())
        failed.refresh_from_db()
        accepted.refresh_from_db()
        assert failed.payload is not None
        assert failed.route is not None
        assert accepted.payload is None
        assert accepted.route is None

    def test_enqueue_uses_parent_workspace_for_child_environment(self) -> None:
        child = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
        )
        ticket = Ticket.objects.create_with_number(
            team=child,
            widget_session_id="",
            distinct_id="slack-child",
            channel_source=Channel.SLACK,
            slack_channel_id="C123",
            slack_thread_ts="1700000000.000100",
        )
        Comment.objects.create(
            team=child,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Support reply",
            created_by=self.user,
            item_context={"author_type": "team", "is_private": False},
        )
        part = ConversationDeliveryPart.objects.unscoped().select_related("delivery").get()
        assert part.team_id == self.team.id
        assert part.delivery.team_id == self.team.id
        assert part.delivery.provider_account_id == "T123"
        assert part.payload is not None
        assert part.payload["media_team_id"] == child.id
        assert part.client_msg_id

    def test_enqueue_ignores_slack_ticket_from_another_team(self) -> None:
        other = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        other_ticket = Ticket.objects.create_with_number(
            team=other,
            widget_session_id="",
            distinct_id="slack-other",
            channel_source=Channel.SLACK,
            slack_channel_id="C999",
            slack_thread_ts="1700000000.000999",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(other_ticket.id),
            content="Support reply",
            created_by=self.user,
            item_context={"author_type": "team", "is_private": False},
        )
        assert not ConversationDeliveryPart.objects.unscoped().exists()

    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email")
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_avatar_lookup_failure_does_not_block_body_post(
        self,
        mock_get_client: MagicMock,
        mock_avatar: MagicMock,
    ) -> None:
        self._create_reply()
        part = self._part()
        mock_avatar.side_effect = _slack_api_error("ratelimited", retry_after="7", status_code=429)
        client = MagicMock()
        client.chat_postMessage.return_value = {"ok": True, "ts": "1700.4"}
        mock_get_client.return_value = client

        process_slack_delivery_part(str(part.id))
        part.refresh_from_db()
        assert part.status == ConversationDeliveryPart.Status.ACCEPTED
        assert part.provider_message_id == "1700.4"
        client.chat_postMessage.assert_called_once()

    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_duplicate_shaped_slack_error_with_ts_is_accepted(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
    ) -> None:
        self._create_reply()
        part = self._part()
        client = MagicMock()
        client.chat_postMessage.side_effect = SlackApiError(
            message="duplicate",
            response=FakeSlackResponse({"ok": False, "error": "fatal_error", "ts": "1700.9"}),
        )
        mock_get_client.return_value = client

        process_slack_delivery_part(str(part.id))
        part.refresh_from_db()
        assert part.status == ConversationDeliveryPart.Status.ACCEPTED
        assert part.provider_message_id == "1700.9"

    def test_redrive_skips_when_workspace_config_is_gone(self) -> None:
        self._create_reply()
        part = self._part()
        now = timezone.now()
        ConversationDeliveryPart.objects.unscoped().filter(id=part.id).update(
            status=ConversationDeliveryPart.Status.FAILED,
            terminal_at=now,
            updated_at=now,
        )
        ConversationDelivery.objects.unscoped().filter(id=part.delivery_id).update(
            status=ConversationDelivery.Status.FAILED,
            terminal_at=now,
            updated_at=now,
        )
        TeamConversationsSlackConfig.objects.filter(team=self.team).delete()

        assert redrive_failed_delivery_part(str(part.id), wake=MagicMock()) is None
        part.refresh_from_db()
        assert part.status == ConversationDeliveryPart.Status.FAILED

    def test_redrive_skips_accepted_parts(self) -> None:
        self._create_reply()
        part = self._part()
        now = timezone.now()
        ConversationDeliveryPart.objects.unscoped().filter(id=part.id).update(
            status=ConversationDeliveryPart.Status.ACCEPTED,
            terminal_at=now,
            accepted_at=now,
            updated_at=now,
        )
        assert redrive_failed_delivery_part(str(part.id), wake=MagicMock()) is None
        part.refresh_from_db()
        assert part.status == ConversationDeliveryPart.Status.ACCEPTED
