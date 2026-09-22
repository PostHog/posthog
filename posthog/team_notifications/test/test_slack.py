from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.team_notifications.slack import SlackChannel, clip_text, find_channel

_TEAM_CHANNEL = SlackChannel(channel_id="C1", shared=False)
_SHARED_CHANNEL = SlackChannel(channel_id="C2", shared=True)
_CHANNELS = {"team-devex": _TEAM_CHANNEL, "partners": _SHARED_CHANNEL}


class TestFindChannel(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain_name", "team-devex", False, _TEAM_CHANNEL, "found"),
            ("leading_hash_is_optional", "#team-devex", False, _TEAM_CHANNEL, "found"),
            ("unknown_name", "team-nobody", False, None, "not_found"),
            ("shared_is_refused_by_default", "partners", False, None, "shared"),
            ("shared_is_allowed_when_chosen", "partners", True, _SHARED_CHANNEL, "found"),
        ]
    )
    def test_lookup(
        self, _name: str, channel_name: str, allow_shared: bool, channel: SlackChannel | None, reason: str
    ) -> None:
        match = find_channel(_CHANNELS, channel_name, allow_shared=allow_shared)

        self.assertEqual((match.channel, match.reason), (channel, reason))


class TestClipText(SimpleTestCase):
    @parameterized.expand(
        [
            ("shorter_than_the_limit_is_untouched", "one line", 20, "one line"),
            ("exactly_the_limit_is_untouched", "one line", 8, "one line"),
            ("over_the_limit_is_cut_to_the_limit", "one line", 4, "one…"),
            ("a_limit_of_zero_keeps_no_text", "one line", 0, "…"),
        ]
    )
    def test_clip(self, _name: str, text: str, limit: int, expected: str) -> None:
        self.assertEqual(clip_text(text, limit), expected)
