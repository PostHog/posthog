from __future__ import annotations

from datetime import datetime

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.conversations.backend.temporal.channel_summary.coordinator import _collect_due_channels
from products.conversations.backend.temporal.channel_summary.summarize import (
    _fetch_period_messages,
    _include_message,
    _slack_permalink,
)
from products.customer_analytics.backend.test.factories import create_account

COORD_MODULE = "products.conversations.backend.temporal.channel_summary.coordinator"


class TestCollectDueChannels(BaseTest):
    def _opt_in_account(self):
        return create_account(
            team_id=self.team.id,
            slack_summary_cadence="daily",
            _properties={"slack_channel_id": "C123"},
        )

    @parameterized.expand(
        [
            ("eligible", True, "xoxb-token", 1),
            # Channel messages go to an LLM; an org without AI data processing approval
            # must never have its channels summarized.
            ("ai_processing_not_approved", False, "xoxb-token", 0),
            ("support_bot_not_configured", True, "", 0),
        ]
    )
    def test_gates_on_org_approval_and_bot_config(self, _name, ai_approved, bot_token, expected_count):
        self._opt_in_account()
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save()

        with patch(f"{COORD_MODULE}.get_support_slack_bot_token", return_value=bot_token):
            due = _collect_due_channels()

        assert len(due) == expected_count
        if due:
            assert due[0].team_id == self.team.id
            assert due[0].slack_channel_id == "C123"
            # Periods cross the activity boundary as parseable ISO strings.
            assert datetime.fromisoformat(due[0].period_start) < datetime.fromisoformat(due[0].period_end)


class TestSummarizeHelpers:
    @parameterized.expand(
        [
            ("parent", "1721999999.123456", None, "https://posthog.slack.com/archives/C1/p1721999999123456"),
            (
                "thread_reply",
                "1722000010.000200",
                "1721999999.123456",
                "https://posthog.slack.com/archives/C1/p1722000010000200?thread_ts=1721999999.123456&cid=C1",
            ),
        ]
    )
    def test_permalinks(self, _name, ts, thread_ts, expected):
        assert _slack_permalink("C1", ts, thread_ts) == expected

    @parameterized.expand(
        [
            ("plain_message", {"text": "hello", "ts": "1"}, True),
            ("thread_broadcast", {"text": "hello", "subtype": "thread_broadcast", "ts": "1"}, True),
            ("join_noise", {"text": "joined", "subtype": "channel_join", "ts": "1"}, False),
            ("bot_post", {"text": "event fired", "subtype": "bot_message", "ts": "1"}, False),
            ("empty_text_no_files", {"text": "  ", "ts": "1"}, False),
            ("file_only", {"text": "", "files": [{"id": "F1"}], "ts": "1"}, True),
        ]
    )
    def test_include_message(self, _name, message, expected):
        assert _include_message(message) is expected

    def test_thread_replies_after_the_period_are_excluded(self):
        parent = {"text": "question", "ts": "100.0", "thread_ts": "100.0", "user": "U1", "reply_count": 2}
        in_window_reply = {"text": "answer", "ts": "150.0", "thread_ts": "100.0", "user": "U2"}
        after_window_reply = {"text": "next week's spoiler", "ts": "999.0", "thread_ts": "100.0", "user": "U2"}
        client = MagicMock()
        client.conversations_history.return_value = {"messages": [parent], "response_metadata": {}}
        client.conversations_replies.return_value = {"messages": [parent, in_window_reply, after_window_reply]}

        threads = _fetch_period_messages(client, "C1", oldest=50.0, latest=200.0)

        assert [(p["ts"], [r["ts"] for r in replies]) for p, replies in threads] == [("100.0", ["150.0"])]
