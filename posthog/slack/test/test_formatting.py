from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.slack.formatting import escape_slack_mrkdwn


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
