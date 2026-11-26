import uuid
from urllib.parse import parse_qs, urlsplit

from posthog.test.base import BaseTest

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.hashers import make_password
from django.test import SimpleTestCase
from django.urls import reverse

from parameterized import parameterized

from posthog.admin.admins.user_admin import UserAdmin, UserChangeForm
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


class TestUserAdminPasswordDisplay(SimpleTestCase):
    @parameterized.expand(
        [
            ("usable", make_password("a-strong-password-123"), "Resetting the password"),
            ("unusable", make_password(None), "No password set."),
        ]
    )
    def test_shows_no_part_of_the_hash(self, _name: str, encoded: str, expected: str):
        user = User(pk=1, email="someone@example.com", password=encoded)

        rendered = str(UserAdmin(User, AdminSite()).password_display(user))

        self.assertIn(expected, rendered)
        for part in encoded.split("$")[1:]:
            self.assertNotIn(part, rendered)

    def test_change_form_has_no_password_field(self):
        # Django's own password field would render the first characters of the salt and hash.
        self.assertNotIn("password", UserChangeForm.base_fields)
