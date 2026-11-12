import re
import html
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

    def test_ticket_is_not_read_as_a_field_lookup(self):
        self._make_user("first-ticket@example.com")
        self._make_user("second-ticket@example.com")

        response = self.client.get(self.changelist, {"q": "ticket@example.com", "ticket": self.ticket})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cl"].result_count, 2)

    def test_each_row_carries_the_ticket_to_the_user_page(self):
        first = self._make_user("first-ticket@example.com")
        self._make_user("second-ticket@example.com")

        response = self.client.get(self.changelist, {"q": "ticket@example.com", "ticket": self.ticket})

        change_url = reverse("admin:posthog_user_change", args=[first.pk])
        hrefs = re.findall(rf'href="{re.escape(change_url)}\?([^"]+)"', response.content.decode())
        self.assertTrue(hrefs)
        for href in hrefs:
            filters = parse_qs(parse_qs(html.unescape(href))["_changelist_filters"][0])
            self.assertEqual(filters["ticket"], [self.ticket])

    def test_a_new_search_keeps_the_ticket(self):
        self._make_user("first-ticket@example.com")
        self._make_user("second-ticket@example.com")

        response = self.client.get(self.changelist, {"q": "ticket@example.com", "ticket": self.ticket})

        self.assertContains(response, f'<input type="hidden" name="ticket" value="{self.ticket}">', html=True)

    @parameterized.expand(
        [
            ("exact", "only-match@example.com", "only-match@example.com"),
            ("searched in another case", "only-match@example.com", "Only-Match@Example.COM"),
            # Accounts from before emails were normalized on signup can still hold mixed case.
            ("stored in another case", "Legacy.Person@Example.com", "legacy.person@example.com"),
            ("padded", "only-match@example.com", "  only-match@example.com\t"),
        ]
    )
    def test_a_single_exact_match_opens_the_user_with_the_ticket(self, _name: str, stored: str, search: str):
        target = self._make_user(stored)

        response = self.client.get(self.changelist, {"q": search, "ticket": self.ticket})

        self.assertEqual(response.status_code, 302)
        location = urlsplit(response["Location"])
        self.assertEqual(location.path, reverse("admin:posthog_user_change", args=[target.pk]))
        query = parse_qs(location.query)
        self.assertEqual(query["ticket"], [self.ticket])
        self.assertEqual(parse_qs(query["_changelist_filters"][0]), {"q": [search]})

    def test_a_single_partial_match_still_shows_the_list(self):
        self._make_user("only-match@example.community")

        response = self.client.get(self.changelist, {"q": "only-match@example.com", "ticket": self.ticket})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cl"].result_count, 1)

    def test_no_match_shows_the_empty_list(self):
        response = self.client.get(self.changelist, {"q": "nobody@example.com", "ticket": self.ticket})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cl"].result_count, 0)

    def test_an_invalid_lookup_still_reports_the_error(self):
        self._make_user("only-match@example.com")

        response = self.client.get(
            self.changelist, {"q": "only-match@example.com", "ticket": self.ticket, "no_such_field": "1"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{self.changelist}?e=1")

    def test_a_single_match_without_a_ticket_still_shows_the_list(self):
        self._make_user("only-match@example.com")

        response = self.client.get(self.changelist, {"q": "only-match@example.com"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cl"].result_count, 1)


class TestUserAdminPasswordDisplay(SimpleTestCase):
    @parameterized.expand(
        [
            ("usable", make_password("a-strong-password-123"), "Algorithm"),
            ("unusable", make_password(None), "No password set."),
            ("unknown_format", "not-a-hash$abc$def", "Unknown password format."),
        ]
    )
    def test_shows_only_the_algorithm(self, _name: str, encoded: str, expected: str):
        user = User(pk=1, email="someone@example.com", password=encoded)

        rendered = str(UserAdmin(User, AdminSite()).password_display(user))

        self.assertIn(expected, rendered)
        for part in encoded.split("$")[1:]:
            self.assertNotIn(part, rendered)

    def test_change_form_has_no_password_field(self):
        # Django's own password field would render the first characters of the salt and hash.
        self.assertNotIn("password", UserChangeForm.base_fields)
