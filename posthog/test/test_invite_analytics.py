import uuid

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from posthog.event_usage import alias_invite_id
from posthog.invite_analytics import invite_analytics_id, invite_distinct_id

INVITE_ID = "0190f1a2-9c8b-7a69-8584-736251403f2e"


class TestInviteAnalytics(SimpleTestCase):
    def test_distinct_id_is_stable_and_hides_the_invite_id(self) -> None:
        distinct_id = invite_distinct_id(INVITE_ID)

        self.assertEqual(distinct_id, invite_distinct_id(uuid.UUID(INVITE_ID)))
        self.assertRegex(distinct_id, r"^invite_[0-9a-f]{32}$")
        self.assertNotIn(INVITE_ID.replace("-", ""), distinct_id)

    def test_hash_does_not_depend_on_the_secret_key(self) -> None:
        with override_settings(SECRET_KEY="a" * 50):
            first = invite_analytics_id(INVITE_ID)
        with override_settings(SECRET_KEY="b" * 50):
            second = invite_analytics_id(INVITE_ID)

        self.assertEqual(first, second)

    @patch("posthog.event_usage.posthoganalytics")
    def test_alias_uses_the_invite_distinct_id(self, posthoganalytics: MagicMock) -> None:
        alias_invite_id(MagicMock(distinct_id="user-distinct-id"), INVITE_ID)

        posthoganalytics.alias.assert_called_once_with("user-distinct-id", invite_distinct_id(INVITE_ID))
