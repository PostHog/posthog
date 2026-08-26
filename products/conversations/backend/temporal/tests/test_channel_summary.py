from __future__ import annotations

from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.conversations.backend.temporal.channel_summary.coordinator import _collect_due_channels
from products.conversations.backend.temporal.channel_summary.summarize import (
    _build_transcript,
    _fetch_period_messages,
    _include_message,
    _message_refs,
    _resolve_mentions,
    _slack_permalink,
)
from products.customer_analytics.backend.facade import api as customer_analytics
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

    def test_one_team_cannot_monopolize_the_per_run_cap(self):
        for i in range(3):
            create_account(
                team_id=self.team.id,
                slack_summary_cadence="daily",
                _properties={"slack_channel_id": f"C{i}"},
            )

        with (
            patch(f"{COORD_MODULE}.get_support_slack_bot_token", return_value="xoxb-token"),
            patch(f"{COORD_MODULE}.MAX_SUMMARIES_PER_TEAM_PER_RUN", 2),
        ):
            due = _collect_due_channels()

        assert len(due) == 2

    @parameterized.expand(
        [
            ("opted_in", "daily", {"slack_channel_id": "C123"}, ("daily", "C123")),
            ("cadence_off", None, {"slack_channel_id": "C123"}, None),
            ("channel_unbound", "daily", {}, None),
        ]
    )
    def test_get_account_slack_summary_binding(self, _name, cadence, properties, expected):
        account = create_account(team_id=self.team.id, slack_summary_cadence=cadence, _properties=properties)

        binding = customer_analytics.get_account_slack_summary_binding(self.team.id, str(account.id))

        if expected is None:
            assert binding is None
        else:
            assert binding is not None
            assert (binding.cadence, binding.slack_channel_id) == expected


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

    def test_truncated_transcript_returns_only_the_kept_threads(self):
        # Audit refs and message_count come from the returned threads: a thread the
        # transcript dropped must drop out of the audit too, or the count overclaims.
        old_thread: tuple[dict, list[dict]] = ({"text": "x" * 300, "ts": "100.0", "user": "U1"}, [])
        new_thread: tuple[dict, list[dict]] = ({"text": "y" * 300, "ts": "200.0", "user": "U1"}, [])
        client = MagicMock()
        team = MagicMock()
        team.timezone_info = UTC

        with patch("products.conversations.backend.temporal.channel_summary.summarize.MAX_TRANSCRIPT_CHARS", 400):
            transcript, covered = _build_transcript(
                client, team, "C1", [old_thread, new_thread], period_start=50.0, cache={"U1": "alice"}
            )

        assert covered == [new_thread]
        assert "(earlier messages omitted: transcript truncated)" in transcript
        assert "yyy" in transcript and "xxx" not in transcript

    def test_message_refs_cover_every_message_with_metadata_only(self):
        parent = {"text": "secret question", "ts": "1721999999.123456", "thread_ts": "1721999999.123456", "user": "U1"}
        reply = {"text": "secret answer", "ts": "1722000010.000200", "thread_ts": "1721999999.123456", "user": "U2"}
        client = MagicMock()
        client.users_info.return_value = {"user": {"profile": {"display_name": "alice", "real_name": "Alice A"}}}

        refs = _message_refs(client, "C1", [(parent, [reply])], cache={"U2": "bob"})

        assert refs == [
            {
                "author": "alice",
                "sent_at": "2024-07-26T13:19:59.123456+00:00",
                "permalink": "https://posthog.slack.com/archives/C1/p1721999999123456",
            },
            {
                "author": "bob",
                "sent_at": "2024-07-26T13:20:10.000200+00:00",
                "permalink": "https://posthog.slack.com/archives/C1/p1722000010000200?thread_ts=1721999999.123456&cid=C1",
            },
        ]
        assert not any("secret" in str(ref) for ref in refs)

    def test_thread_replies_after_the_period_are_excluded(self):
        parent = {"text": "question", "ts": "100.0", "thread_ts": "100.0", "user": "U1", "reply_count": 2}
        in_window_reply = {"text": "answer", "ts": "150.0", "thread_ts": "100.0", "user": "U2"}
        after_window_reply = {"text": "next week's spoiler", "ts": "999.0", "thread_ts": "100.0", "user": "U2"}
        client = MagicMock()
        client.conversations_history.return_value = {"messages": [parent], "response_metadata": {}}
        client.conversations_replies.return_value = {"messages": [parent, in_window_reply, after_window_reply]}

        threads = _fetch_period_messages(client, "C1", oldest=50.0, latest=200.0)

        assert [(p["ts"], [r["ts"] for r in replies]) for p, replies in threads] == [("100.0", ["150.0"])]

    def test_replies_to_a_thread_started_before_the_period_are_included(self):
        # Thread replies never appear in channel history, so without the lookback scan a
        # reply inside the period to last week's thread would vanish from the summary.
        stale_parent = {
            "text": "old question",
            "ts": "10.0",
            "thread_ts": "10.0",
            "user": "U1",
            "reply_count": 2,
            "latest_reply": "150.0",
        }
        quiet_old_parent = {
            "text": "no new replies",
            "ts": "20.0",
            "user": "U1",
            "reply_count": 1,
            "latest_reply": "30.0",
        }
        # latest_reply lands in the window, but the reply itself falls outside it — the
        # parent must not surface as period activity.
        phantom_parent = {
            "text": "old demo",
            "ts": "15.0",
            "thread_ts": "15.0",
            "user": "U1",
            "reply_count": 1,
            "latest_reply": "150.0",
        }
        before_window_reply = {"text": "old answer", "ts": "30.0", "thread_ts": "10.0", "user": "U2"}
        in_window_reply = {"text": "new answer", "ts": "150.0", "thread_ts": "10.0", "user": "U2"}

        def history(channel, oldest, latest, limit, cursor):
            in_window_scan = float(oldest) == 50.0
            return {
                "messages": [] if in_window_scan else [stale_parent, quiet_old_parent, phantom_parent],
                "response_metadata": {},
            }

        def replies(channel, ts, limit, cursor):
            if ts == "10.0":
                return {"messages": [stale_parent, before_window_reply, in_window_reply]}
            return {"messages": [phantom_parent, {"text": "late", "ts": "999.0", "thread_ts": "15.0", "user": "U2"}]}

        client = MagicMock()
        client.conversations_history.side_effect = history
        client.conversations_replies.side_effect = replies

        threads = _fetch_period_messages(client, "C1", oldest=50.0, latest=200.0)

        assert [(p["ts"], [r["ts"] for r in replies]) for p, replies in threads] == [("10.0", ["150.0"])]

    def test_thread_replies_paginate_past_the_first_page(self):
        parent = {"text": "question", "ts": "100.0", "thread_ts": "100.0", "user": "U1", "reply_count": 2}
        page_one_reply = {"text": "first", "ts": "110.0", "thread_ts": "100.0", "user": "U2"}
        page_two_reply = {"text": "second", "ts": "120.0", "thread_ts": "100.0", "user": "U2"}
        client = MagicMock()
        client.conversations_history.return_value = {"messages": [parent], "response_metadata": {}}
        client.conversations_replies.side_effect = [
            {"messages": [parent, page_one_reply], "response_metadata": {"next_cursor": "cur1"}},
            {"messages": [page_two_reply], "response_metadata": {}},
        ]

        threads = _fetch_period_messages(client, "C1", oldest=50.0, latest=200.0)

        assert [r["ts"] for r in threads[0][1]] == ["110.0", "120.0"]
        assert client.conversations_replies.call_args_list[1].kwargs["cursor"] == "cur1"

    def test_mentions_in_text_resolve_to_display_names(self):
        client = MagicMock()
        client.users_info.return_value = {"user": {"profile": {"display_name": "alice", "real_name": "Alice A"}}}
        cache: dict[str, str] = {}

        resolved = _resolve_mentions(client, "hey <@U123ABC> and <@U123ABC|alice-legacy>, ping me", cache)

        assert resolved == "hey @alice and @alice, ping me"
        client.users_info.assert_called_once_with(user="U123ABC")
