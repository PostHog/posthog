import uuid
from urllib.parse import parse_qs, urlsplit

from posthog.test.base import BaseTest

from django.urls import reverse

from parameterized import parameterized

from posthog.admin.admins.user_admin import UserChangeForm
from posthog.models import User


class TestUserAdminTicketParam(BaseTest):
    ticket = "https://hogdesk.example.com/tickets/74947"

    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.changelist = reverse("admin:posthog_user_changelist")

    def _make_user(self, email: str) -> User:
        return User.objects.create(email=email, distinct_id=str(uuid.uuid4()))

    @parameterized.expand(
        [
            ("exact", "only-match@example.com", "only-match@example.com"),
            ("searched in another case", "only-match@example.com", "Only-Match@Example.COM"),
            # Accounts from before emails were normalized on signup can still hold mixed case.
            ("stored in another case", "Legacy.Person@Example.com", "legacy.person@example.com"),
            ("padded", "only-match@example.com", "  only-match@example.com\t"),
        ]
    )
    def test_an_exact_match_opens_the_console_user_page_with_the_ticket(self, _name: str, stored: str, search: str):
        target = self._make_user(stored)

        response = self.client.get(self.changelist, {"q": search, "ticket": self.ticket})

        self.assertEqual(response.status_code, 302)
        location = urlsplit(response["Location"])
        self.assertEqual(location.path, reverse("admin_console_user", kwargs={"pk": target.pk}))
        self.assertEqual(parse_qs(location.query), {"ticket": [self.ticket]})

    @parameterized.expand(
        [
            ("partial match", ["only-match@example.community"], 1),
            ("two accounts differ only by case", ["only-match@example.com", "Only-Match@example.com"], 2),
            ("no match", [], 0),
        ]
    )
    def test_without_an_exact_match_the_list_shows_without_the_ticket(
        self, _name: str, stored: list[str], expected_count: int
    ):
        for email in stored:
            self._make_user(email)

        response = self.client.get(self.changelist, {"q": "only-match@example.com", "ticket": self.ticket})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{self.changelist}?q=only-match%40example.com")
        listed = self.client.get(response["Location"])
        self.assertEqual(listed.context["cl"].result_count, expected_count)

    def test_a_single_match_without_a_ticket_still_shows_the_list(self):
        self._make_user("only-match@example.com")

        response = self.client.get(self.changelist, {"q": "only-match@example.com"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cl"].result_count, 1)


class TestUserChangeFormPasswordField(BaseTest):
    def test_password_field_omits_salt_and_hash(self):
        # Guards against the partial (masked) hash material Django's default widget shows reappearing.
        user = User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))
        # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password (test fixture, not a user-facing password-set path)
        user.set_password("a-strong-password-123")
        user.save()

        rendered = str(UserChangeForm(instance=user)["password"])

        self.assertIn("algorithm", rendered)
        self.assertNotIn("salt", rendered)
        self.assertNotIn("hash", rendered)

    def test_password_field_help_text_omits_reset_link(self):
        # A raw reset link/token in the help text would let a staff member reset the user's
        # password themselves; the "Reset password" button emails it to the user instead.
        user = User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

        help_text = UserChangeForm(instance=user).fields["password"].help_text

        self.assertNotIn("/reset/", help_text)
        self.assertNotIn("href", help_text)
