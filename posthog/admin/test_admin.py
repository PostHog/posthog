from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib import admin
from django.contrib.admin import AdminSite
from django.test import RequestFactory

from posthog.admin import register_all_admin
from posthog.admin.admins.user_admin import UserAdmin
from posthog.admin.inlines.organization_member_inline import OrganizationMemberForUserInline, OrganizationMemberInline
from posthog.admin.inlines.plugin_attachment_inline import PluginAttachmentInline
from posthog.models import User


class TestAdmin(BaseTest):
    def test_register_admin_models_succeeds(self):
        with patch.object(admin, "site", AdminSite()):
            register_all_admin()


class TestUserAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user_admin = UserAdmin(User, AdminSite())
        self.request_factory = RequestFactory()

    def search_user_ids(self, search_term: str) -> list[int]:
        request = self.request_factory.get("/admin/posthog/user/", {"q": search_term})
        queryset, _use_distinct = self.user_admin.get_search_results(request, User.objects.all(), search_term)
        return list(queryset.values_list("id", flat=True))

    def test_search_by_distinct_id_returns_matching_user(self) -> None:
        matching_user = User.objects.create_user(
            email="distinct-admin-search@example.com",
            password=None,
            first_name="",
            distinct_id="billing-distinct-id",
        )
        User.objects.create_user(
            email="other-admin-search@example.com",
            password=None,
            first_name="",
            distinct_id="other-distinct-id",
        )

        assert self.search_user_ids("billing-distinct-id") == [matching_user.id]

    def test_search_by_email_still_returns_matching_user(self) -> None:
        matching_user = User.objects.create_user(
            email="email-admin-search@example.com",
            password=None,
            first_name="",
            distinct_id="email-search-distinct-id",
        )

        assert self.search_user_ids("email-admin-search@example.com") == [matching_user.id]

    def test_non_matching_distinct_id_returns_no_users(self) -> None:
        User.objects.create_user(
            email="nonmatch-admin-search@example.com",
            password=None,
            first_name="",
            distinct_id="known-distinct-id",
        )

        assert self.search_user_ids("missing-distinct-id") == []


class TestPluginAttachmentInline(BaseTest):
    def test_parsed_json_escapes_html_in_values(self):
        inline = PluginAttachmentInline(MagicMock(), MagicMock())
        attachment = MagicMock()
        attachment.file_size = 100
        attachment.contents = b'{"xss": "</pre><script>alert(1)</script><pre>"}'

        result = str(inline.parsed_json(attachment))

        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_parsed_json_error_escapes_html(self):
        inline = PluginAttachmentInline(MagicMock(), MagicMock())
        attachment = MagicMock()
        attachment.file_size = 100
        attachment.contents = b"not json"

        result = str(inline.parsed_json(attachment))

        assert "cannot preview:" in result

    def test_raw_contents_error_escapes_html(self):
        inline = PluginAttachmentInline(MagicMock(), MagicMock())
        attachment = MagicMock()
        attachment.file_size = 2 * 1024 * 1024

        result = str(inline.raw_contents(attachment))

        assert "cannot preview:" in result


class TestOrganizationMemberInlineConfig(BaseTest):
    def test_invited_by_is_readonly_and_never_rendered_as_user_select(self):
        # Regression guard: invited_by must not become an editable FK select in admin inlines.
        assert "invited_by" in OrganizationMemberInline.fields
        assert "invited_by" in OrganizationMemberInline.readonly_fields
        assert "invited_by" in OrganizationMemberForUserInline.fields
        assert "invited_by" in OrganizationMemberForUserInline.readonly_fields
