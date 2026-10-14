import re
import html
import uuid
from importlib import import_module
from urllib.parse import parse_qs, urlencode, urlsplit

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.contrib.admin import ModelAdmin
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.db.models import PROTECT
from django.test import RequestFactory
from django.urls import reverse

from loginas import settings as la_settings
from parameterized import parameterized

from posthog.admin.admins.user_admin import UserAdmin, UserChangeForm
from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.session.models import Session
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed


class _RefusesDeletionAdmin(ModelAdmin):
    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class TestUserAdminSessions(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)
        self.admin = UserAdmin(User, AdminSite())

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _login_session(self, user: User) -> str:
        store = self.engine.SessionStore()
        store[SESSION_KEY] = str(user.pk)
        store.create()
        return store.session_key

    def test_delete_user_sessions_revokes_all_of_the_users_sessions(self):
        user = self._make_user()
        other_user = self._make_user()
        keys = [self._login_session(user), self._login_session(user)]
        other_key = self._login_session(other_user)

        count = self.admin.delete_user_sessions(user)

        self.assertEqual(count, 2)
        self.assertFalse(Session.objects.filter(session_key__in=keys).exists())
        self.assertTrue(Session.objects.filter(session_key=other_key).exists())  # other user untouched


class TestUserAdminPasswordReset(BaseTest):
    def setUp(self):
        super().setUp()
        self.admin = UserAdmin(User, AdminSite())

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _request(self, method: str = "post", data: dict | None = None):
        request = getattr(RequestFactory(), method)("/", data or {})
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_user_change_password_redirects_instead_of_erroring(self):
        # Guards the reported 500: change_password_form is None, so without this override Django's
        # inherited password view crashes with TypeError instead of redirecting to the change page.
        user = self._make_user()

        response = self.admin.user_change_password(self._request(method="get"), user.pk)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin:posthog_user_change", args=[user.pk]))

    @patch("posthog.admin.admins.user_admin.send_password_reset")
    def test_send_password_reset_sets_timestamp_and_dispatches_email(self, mock_send_password_reset):
        user = self._make_user()
        self.assertIsNone(user.requested_password_reset_at)

        response = self.admin.change_view(self._request(data={"send_password_reset": "1"}), str(user.pk))

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertIsNotNone(user.requested_password_reset_at)
        mock_send_password_reset.delay.assert_called_once()
        user_pk, token = mock_send_password_reset.delay.call_args.args[:2]
        self.assertEqual(user_pk, user.pk)
        # A usable reset token must be forwarded — an empty/None token would email a dead link.
        self.assertIsInstance(token, str)
        self.assertTrue(token)


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

    @parameterized.expand([("send_verification",), ("revoke_sessions",), ("send_2fa_reset",), ("send_password_reset",)])
    @patch("posthog.admin.admins.user_admin.send_password_reset")
    @patch("posthog.admin.admins.user_admin.email_verification_code_verifier")
    def test_a_support_action_keeps_the_ticket(self, action: str, *_mocks) -> None:
        target = self._make_user("only-match@example.com")
        change_url = reverse("admin:posthog_user_change", args=[target.pk])
        query = urlencode({"ticket": self.ticket, "_changelist_filters": "q=only-match%40example.com"})

        response = self.client.post(f"{change_url}?{query}", {action: "1"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{change_url}?{query}")


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


class TestUserAdminDeletion(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = UserAdmin(User, AdminSite())
        self.target = User.objects.create_and_join(self.organization, "delete-me@example.com", None)
        self.delete_path = f"/admin/posthog/user/{self.target.pk}/delete/"

    def _request(self, method: str = "post", data: dict | None = None):
        request = getattr(self.factory, method)(self.delete_path, data or {})
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)
        # Django's delete view is wrapped in csrf_protect, which a RequestFactory POST can't satisfy.
        request._dont_enforce_csrf_checks = True
        return request

    def _deletion_logs(self):
        return ActivityLog.objects.filter(scope="User", activity="deleted", item_id=str(self.target.pk))

    def test_confirmation_page_counts_the_cascade_instead_of_listing_every_row(self):
        # The reported timeout: Django's NestedObjects collector loads and renders every cascading
        # row, and recorded views alone run into the millions on a long-lived account.
        for session_id in ("one", "two"):
            SessionRecordingViewed.objects.create(team=self.team, user=self.target, session_id=session_id)

        deleted_objects, model_count, perms_needed, protected = self.admin.get_deleted_objects(
            [self.target], self._request(method="get")
        )

        self.assertEqual(deleted_objects, [])
        self.assertEqual(perms_needed, set())
        self.assertEqual(protected, [])
        self.assertEqual(model_count[str(User._meta.verbose_name_plural)], "1")
        self.assertEqual(model_count[str(SessionRecordingViewed._meta.verbose_name_plural)], "2")
        self.assertEqual(model_count[str(OrganizationMembership._meta.verbose_name_plural)], "1")

    @patch("posthog.admin.admins.user_admin.DELETION_SUMMARY_COUNT_CAP", 1)
    def test_confirmation_page_caps_each_count(self):
        for session_id in ("one", "two", "three"):
            SessionRecordingViewed.objects.create(team=self.team, user=self.target, session_id=session_id)

        _, model_count, _, _ = self.admin.get_deleted_objects([self.target], self._request(method="get"))

        self.assertEqual(model_count[str(SessionRecordingViewed._meta.verbose_name_plural)], "1+")

    def test_confirmation_page_asks_for_a_reason(self):
        response = self.admin.delete_view(self._request(method="get"), str(self.target.pk))
        response.render()

        self.assertIn('name="deletion_reason"', response.content.decode())

    def test_delete_without_a_reason_keeps_the_user(self):
        response = self.admin.delete_view(self._request(data={"post": "yes"}), str(self.target.pk))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.delete_path)
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())

    def test_delete_with_a_reason_records_it_for_every_organization(self):
        other_organization, _, _ = User.objects.bootstrap("Other org", "owner@example.com", None)
        self.target.join(organization=other_organization)
        target_id = self.target.pk

        response = self.admin.delete_view(
            self._request(data={"post": "yes", "deletion_reason": "Duplicate account after an email change"}),
            str(target_id),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=target_id).exists())
        logs = self._deletion_logs()
        self.assertEqual(
            {log.organization_id for log in logs},
            {self.organization.id, other_organization.id},
        )
        for log in logs:
            self.assertEqual(log.user, self.user)
            self.assertEqual(
                (log.detail or {}).get("context"),
                {"reason": "Duplicate account after an email change", "email": "delete-me@example.com"},
            )

    def test_delete_records_the_reason_in_the_admin_log(self):
        # An ActivityLog row needs an organization or team to be scoped to, so a user who has left
        # every organization would otherwise have their deletion recorded with no reason at all.
        self.target.organization_memberships.all().delete()
        target_id = self.target.pk

        self.admin.delete_view(
            self._request(data={"post": "yes", "deletion_reason": "Requested by the customer"}),
            str(target_id),
        )

        self.assertFalse(User.objects.filter(pk=target_id).exists())
        self.assertFalse(self._deletion_logs().exists())
        entry = LogEntry.objects.get(object_id=str(target_id), action_flag=DELETION)
        self.assertIn("Requested by the customer", entry.change_message)

    def test_staff_cannot_delete_the_account_they_are_acting_as(self):
        request = self._request()

        self.assertFalse(self.admin.has_delete_permission(request, self.user))
        self.assertTrue(self.admin.has_delete_permission(request, self.target))

    def test_staff_cannot_delete_the_account_they_are_impersonating(self):
        # AdminImpersonationMiddleware swaps `request.user` back to the staff operator on /admin/
        # paths, so a check against `request.user` alone lets the impersonated account through.
        request = self._request()
        request.session = {
            la_settings.USER_SESSION_FLAG: "signed-original-user",
            SESSION_KEY: str(self.target.pk),
            BACKEND_SESSION_KEY: "django.contrib.auth.backends.ModelBackend",
        }

        self.assertFalse(self.admin.has_delete_permission(request, self.target))

    def test_a_protected_relation_blocks_the_delete_instead_of_failing_part_way_through(self):
        # No relation to User is PROTECT or RESTRICT today. When one lands, reporting no protected
        # objects would let the confirmation page take the reason and then raise ProtectedError from
        # inside the delete, with part of the cascade already gone.
        membership_user_field = OrganizationMembership._meta.get_field("user")
        target_id = self.target.pk

        with patch.object(membership_user_field.remote_field, "on_delete", PROTECT):
            _, _, _, protected = self.admin.get_deleted_objects([self.target], self._request(method="get"))
            self.admin.delete_view(
                self._request(data={"post": "yes", "deletion_reason": "Duplicate account"}),
                str(target_id),
            )

        self.assertEqual(len(protected), 1)
        self.assertTrue(User.objects.filter(pk=target_id).exists())

    @parameterized.expand([("with recorded views", 1, True), ("without recorded views", 0, False)])
    def test_an_admin_that_refuses_deletion_blocks_the_cascade_through_its_model(
        self, _name: str, view_count: int, blocked: bool
    ):
        # Django reports such a model in `perms_needed`, which withholds the confirm button and
        # raises PermissionDenied on the POST. Reporting none would hard-delete rows behind the
        # back of an admin that refuses deletion, such as the one for AI assistant conversations.
        site = AdminSite()
        site.register(SessionRecordingViewed, _RefusesDeletionAdmin)
        admin_with_registry = UserAdmin(User, site)
        for index in range(view_count):
            SessionRecordingViewed.objects.create(team=self.team, user=self.target, session_id=str(index))
        target_id = self.target.pk

        _, _, perms_needed, _ = admin_with_registry.get_deleted_objects([self.target], self._request(method="get"))

        self.assertEqual(perms_needed, {str(SessionRecordingViewed._meta.verbose_name)} if blocked else set())
        request = self._request(data={"post": "yes", "deletion_reason": "Duplicate account"})
        if blocked:
            with self.assertRaises(PermissionDenied):
                admin_with_registry.delete_view(request, str(target_id))
        else:
            admin_with_registry.delete_view(request, str(target_id))
        self.assertEqual(User.objects.filter(pk=target_id).exists(), blocked)

    def test_bulk_delete_action_is_unavailable(self):
        self.assertNotIn("delete_selected", self.admin.get_actions(self._request(method="get")))
