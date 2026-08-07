import uuid

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
        # changelist_view gates the redirect on view/change permission; is_staff grants it
        # (User.is_superuser is a read-only property returning is_staff — it has no setter).
        self.user.is_staff = True
        self.user.save()
        self.admin = UserAdmin(User, AdminSite())

    def _request(self, params):
        request = RequestFactory().get("/admin/posthog/user/", params)
        request.user = self.user
        return request

    def test_email_and_ticket_redirects_to_change_page(self):
        target = self._create_user("customer@example.com")

        response = self.admin.changelist_view(self._request({"q": "customer@example.com", "ticket": "1234"}))

        assert isinstance(response, HttpResponseRedirect)
        assert response.url == f"{reverse('admin:posthog_user_change', args=[target.pk])}?ticket=1234"

    def test_email_match_is_case_insensitive(self):
        # Emails are stored lowercased, so a differently-cased paste still resolves via iexact.
        target = self._create_user("customer@example.com")

        response = self.admin.changelist_view(self._request({"q": "Customer@Example.com", "ticket": "1234"}))

        assert isinstance(response, HttpResponseRedirect)
        assert response.url == f"{reverse('admin:posthog_user_change', args=[target.pk])}?ticket=1234"

    def test_no_ticket_falls_through_to_changelist(self):
        self._create_user("customer@example.com")
        request = self._request({"q": "customer@example.com"})

        with patch.object(ModelAdmin, "changelist_view", return_value=_FELL_THROUGH):
            result = self.admin.changelist_view(request)

        assert result is _FELL_THROUGH

    def test_ambiguous_case_variant_match_falls_through(self):
        # Legacy/direct inserts bypass EmailNormalizer, so case variants of one address can coexist
        # (the DB unique index is case-sensitive). An iexact lookup then matches both — we must refuse
        # to redirect rather than impersonate whichever sorts first.
        self._create_user("customer@example.com")
        User.objects.create(email="Customer@example.com", distinct_id=str(uuid.uuid4()))
        request = self._request({"q": "customer@example.com", "ticket": "1234"})

        with patch.object(ModelAdmin, "changelist_view", return_value=_FELL_THROUGH):
            result = self.admin.changelist_view(request)

        assert result is _FELL_THROUGH

    def test_no_match_falls_through_and_strips_ticket(self):
        # No user matches, so we delegate to the normal changelist — but `ticket` must be stripped
        # first, else Django treats it as an invalid field lookup and redirects to a ?e=1 error page.
        request = self._request({"q": "nobody@example.com", "ticket": "1234"})

        with patch.object(ModelAdmin, "changelist_view", return_value=_FELL_THROUGH):
            result = self.admin.changelist_view(request)

        assert result is _FELL_THROUGH
        assert "ticket" not in request.GET
