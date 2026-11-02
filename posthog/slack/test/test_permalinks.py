from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.slack.permalinks import SlackMessageLink, parse_message_link


class TestParseMessageLink(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "root_copied_in_workspace",
                "https://posthog.slack.com/archives/C0123ABCDEF/p1767225636295669",
                SlackMessageLink(channel_id="C0123ABCDEF", message_ts="1767225636.295669", thread_ts=None),
            ),
            (
                "reply_names_its_thread",
                "https://posthog.slack.com/archives/C0123ABCDEF/p1767225999000100?thread_ts=1767225636.295669&cid=C0123ABCDEF",
                SlackMessageLink(
                    channel_id="C0123ABCDEF", message_ts="1767225999.000100", thread_ts="1767225636.295669"
                ),
            ),
            (
                # The form PostHog itself builds for a mirrored discussion.
                "app_host",
                "https://app.slack.com/archives/C1/p1700000000000100",
                SlackMessageLink(channel_id="C1", message_ts="1700000000.000100", thread_ts=None),
            ),
            (
                "enterprise_grid_and_surrounding_whitespace",
                "  https://acme.enterprise.slack.com/archives/G01/p1700000000000100/ ",
                SlackMessageLink(channel_id="G01", message_ts="1700000000.000100", thread_ts=None),
            ),
            (
                "malformed_thread_ts_is_dropped_not_trusted",
                "https://posthog.slack.com/archives/C1/p1700000000000100?thread_ts=abc",
                SlackMessageLink(channel_id="C1", message_ts="1700000000.000100", thread_ts=None),
            ),
        ]
    )
    def test_reads_a_message_link(self, _name: str, url: str, expected: SlackMessageLink) -> None:
        assert parse_message_link(url) == expected

    @parameterized.expand(
        [
            ("channel_only", "https://posthog.slack.com/archives/C0123ABCDEF"),
            ("not_slack", "https://example.com/archives/C1/p1700000000000100"),
            ("lookalike_host", "https://slack.com.evil.example/archives/C1/p1700000000000100"),
            ("plain_http", "http://posthog.slack.com/archives/C1/p1700000000000100"),
            ("short_ts", "https://posthog.slack.com/archives/C1/p17000000"),
            ("not_a_url", "C1/p1700000000000100"),
        ]
    )
    def test_refuses_anything_else(self, _name: str, url: str) -> None:
        assert parse_message_link(url) is None
