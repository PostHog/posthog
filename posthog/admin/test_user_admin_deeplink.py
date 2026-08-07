from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin import ModelAdmin
from django.contrib.admin.sites import AdminSite
from django.http import HttpResponseRedirect
from django.test import RequestFactory
from django.urls import reverse

from posthog.admin.admins.user_admin import UserAdmin
from posthog.models import User

_FELL_THROUGH = object()


class TestUserAdminImpersonationDeepLink(BaseTest):
    """The changelist redirects an email + ticket deep-link straight to the user's change page,
    so support tooling that only knows the customer's email can reach the "Log in as" flow."""

    def setUp(self):
        super().setUp()
        # changelist_view gates the redirect on view/change permission.
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        self.admin = UserAdmin(User, AdminSite())

    def _changelist(self, params):
        request = RequestFactory().get("/admin/posthog/user/", params)
        request.user = self.user
        # Stub the parent changelist so the non-redirect path doesn't render the full page.
        with patch.object(ModelAdmin, "changelist_view", return_value=_FELL_THROUGH):
            return self.admin.changelist_view(request)

    def test_email_and_ticket_redirects_to_change_page(self):
        target = self._create_user("customer@example.com")

        response = self._changelist({"q": "customer@example.com", "ticket": "1234"})

        assert isinstance(response, HttpResponseRedirect)
        assert response.url == f"{reverse('admin:posthog_user_change', args=[target.pk])}?ticket=1234"

    def test_email_match_is_case_insensitive(self):
        target = self._create_user("customer@example.com")

        response = self._changelist({"q": "Customer@Example.com", "ticket": "1234"})

        assert isinstance(response, HttpResponseRedirect)
        assert response.url.startswith(reverse("admin:posthog_user_change", args=[target.pk]))

    def test_without_ticket_falls_through_to_changelist(self):
        self._create_user("customer@example.com")

        assert self._changelist({"q": "customer@example.com"}) is _FELL_THROUGH

    def test_no_match_falls_through_to_changelist(self):
        assert self._changelist({"q": "nobody@example.com", "ticket": "1234"}) is _FELL_THROUGH

    def test_ambiguous_case_variant_match_falls_through(self):
        # email uniqueness is case-sensitive, so case-variant accounts can coexist. An ambiguous
        # iexact match must not silently redirect to an arbitrary one.
        self._create_user("customer@example.com")
        self._create_user("Customer@example.com")

        assert self._changelist({"q": "customer@example.com", "ticket": "1234"}) is _FELL_THROUGH
