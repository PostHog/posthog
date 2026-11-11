from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.slack.formatting import escape_slack_mrkdwn, markdown_links_to_labels


class TestEscapeSlackMrkdwn(SimpleTestCase):
    @parameterized.expand(
        [
            ("link_injection", "<https://evil|click>", "&lt;https://evil|click&gt;"),
            ("ampersand", "Tom & Jerry", "Tom &amp; Jerry"),
            ("plain", "Alice", "Alice"),
        ]
    )
    def test_escapes_slack_control_chars(self, _name, raw, expected):
        assert escape_slack_mrkdwn(raw) == expected


class TestMarkdownLinksToLabels(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain_link", "See [the funnel](https://us.posthog.com/project/2/insights/a).", "See the funnel."),
            (
                "sql_link_with_nested_parentheses",
                "Ran [errors](https://us.posthog.com/project/2/sql?open_query=SELECT%20count(if(x))%20FROM%20events) today",
                "Ran errors today",
            ),
            ("angle_bracket_destination", "[q](<https://x.example/sql?open_query=SELECT 1>)", "q"),
            ("link_with_title", '[chart](https://x.example/a "caption")', "chart"),
            ("image_stays", "![img](https://x.example/a.png)", "![img](https://x.example/a.png)"),
            ("bracketed_text_stays", "See [1] and arr[0]", "See [1] and arr[0]"),
            ("no_links", "plain **bold** text", "plain **bold** text"),
        ]
    )
    def test_replaces_links_with_labels(self, _name, raw, expected):
        assert markdown_links_to_labels(raw) == expected
