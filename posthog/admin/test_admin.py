from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib import admin
from django.contrib.admin import AdminSite
from django.test import RequestFactory

from posthog.admin import _OAUTH_ADMIN_MODEL_NAMES, install_admin_app_list_overrides, register_all_admin
from posthog.admin.admins.user_admin import UserAdmin
from posthog.admin.inlines.organization_member_inline import OrganizationMemberForUserInline, OrganizationMemberInline
from posthog.admin.inlines.plugin_attachment_inline import PluginAttachmentInline
from posthog.models import User


class TestAdmin(BaseTest):
    def test_register_admin_models_succeeds(self):
        with patch.object(admin, "site", AdminSite()):
            register_all_admin()


class TestOAuthSidebarRegrouping(BaseTest):
    def _patched_get_app_list(self):
        site = AdminSite()
        site.get_app_list = lambda request, app_label=None: [  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
            {
                "name": "PostHog",
                "app_label": "posthog",
                "app_url": "/admin/posthog/",
                "has_module_perms": True,
                "models": [
                    {"name": "OAuth applications", "object_name": "OAuthApplication"},
                    {"name": "OAuth access tokens", "object_name": "OAuthAccessToken"},
                    {"name": "OAuth grants", "object_name": "OAuthGrant"},
                    {"name": "OAuth ID tokens", "object_name": "OAuthIDToken"},
                    {"name": "OAuth refresh tokens", "object_name": "OAuthRefreshToken"},
                    {"name": "Users", "object_name": "User"},
                ]
                if app_label in (None, "posthog")
                else [],
            }
        ]
        with patch.object(admin, "site", site):
            install_admin_app_list_overrides()
            return site.get_app_list

    def test_oauth_models_moved_to_oauth_section(self):
        get_app_list = self._patched_get_app_list()
        result = get_app_list(request=None)

        oauth_apps = [app for app in result if app["app_label"] == "oauth"]
        assert len(oauth_apps) == 1
        oauth_object_names = {model["object_name"] for model in oauth_apps[0]["models"]}
        assert oauth_object_names == _OAUTH_ADMIN_MODEL_NAMES

        posthog_apps = [app for app in result if app["app_label"] == "posthog"]
        assert len(posthog_apps) == 1
        posthog_object_names = {model["object_name"] for model in posthog_apps[0]["models"]}
        assert posthog_object_names == {"User"}

    def test_oauth_app_label_returns_only_oauth_models(self):
        get_app_list = self._patched_get_app_list()
        result = get_app_list(request=None, app_label="oauth")

        assert len(result) == 1
        assert result[0]["app_label"] == "oauth"
        assert result[0]["name"] == "OAuth"
        assert {model["object_name"] for model in result[0]["models"]} == _OAUTH_ADMIN_MODEL_NAMES


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
