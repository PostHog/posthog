from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.models import User, UserPersonalization

ROSTER_PAYLOAD = {
    "data": {
        "team": {
            "teamMembers": [
                {"firstName": "Raquel", "lastName": "Smith", "avatar": {"url": "https://cdn/raquel.png"}},
                {"firstName": "James", "lastName": "Hawkins", "avatar": {"url": "https://cdn/james-h.png"}},
                {"firstName": "James", "lastName": "Hawkins", "avatar": {"url": "https://cdn/other-james-h.png"}},
                {"firstName": "NoPhoto", "lastName": "Person", "avatar": None},
            ]
        }
    }
}


def avatar_of(user: User) -> Any:
    personalization = UserPersonalization.objects.filter(user=user).first()
    return personalization.avatar_url if personalization else None


@patch(
    "posthog.management.commands.backfill_staff_avatar_urls._fetch_json",
    return_value=ROSTER_PAYLOAD,
)
class TestBackfillStaffAvatarUrls(BaseTest):
    def _create_staff_user(self, email: str, first_name: str, last_name: str = "", **kwargs: Any) -> User:
        user = User.objects.create_user(email=email, password=None, first_name=first_name, **kwargs)
        user.last_name = last_name
        user.save()
        return user

    def test_matches_staff_by_name_and_skips_ambiguous_and_non_staff(self, _mock_fetch: Any) -> None:
        matched = self._create_staff_user("raquel@posthog.com", "Raquel", "Smith")
        full_name_in_first = self._create_staff_user("raquel2@posthog.com", "Raquel Smith")
        ambiguous = self._create_staff_user("james.h@posthog.com", "James", "Hawkins")
        non_staff = self._create_staff_user("raquel@example.com", "Raquel", "Smith")

        call_command("backfill_staff_avatar_urls")

        self.assertEqual(avatar_of(matched), "https://cdn/raquel.png")
        self.assertEqual(avatar_of(full_name_in_first), "https://cdn/raquel.png")
        self.assertIsNone(avatar_of(ambiguous))
        self.assertIsNone(avatar_of(non_staff))

    def test_dry_run_writes_nothing(self, _mock_fetch: Any) -> None:
        user = self._create_staff_user("raquel@posthog.com", "Raquel", "Smith")
        call_command("backfill_staff_avatar_urls", "--dry-run")
        self.assertIsNone(avatar_of(user))

    def test_existing_avatar_kept_unless_overwrite(self, _mock_fetch: Any) -> None:
        user = self._create_staff_user("raquel@posthog.com", "Raquel", "Smith")
        UserPersonalization.objects.create(user=user, avatar_url="https://example.com/custom.png")

        call_command("backfill_staff_avatar_urls")
        self.assertEqual(avatar_of(user), "https://example.com/custom.png")

        call_command("backfill_staff_avatar_urls", "--overwrite")
        self.assertEqual(avatar_of(user), "https://cdn/raquel.png")
