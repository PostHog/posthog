from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib import admin
from django.contrib.admin import AdminSite

from posthog.admin import register_all_admin
from posthog.admin.inlines.organization_member_inline import OrganizationMemberForUserInline, OrganizationMemberInline
from posthog.admin.inlines.plugin_attachment_inline import PluginAttachmentInline


class TestAdmin(BaseTest):
    def test_register_admin_models_succeeds(self):
        with patch.object(admin, "site", AdminSite()):
            register_all_admin()


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
