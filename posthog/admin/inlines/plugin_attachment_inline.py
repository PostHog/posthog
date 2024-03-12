import json

from django.contrib import admin
from django.utils.html import format_html

from posthog.models import PluginAttachment

ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES = 1024 * 1024


class PluginAttachmentInline(admin.StackedInline):
    extra = 0
    model = PluginAttachment
    fields = ("key", "content_type", "file_size", "raw_contents", "json_contents")
    readonly_fields = fields

    def raw_contents(self, attachment: PluginAttachment):
        try:
            if attachment.file_size > ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES:
                raise ValueError(
                    f"file size {attachment.file_size} is larger than {ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES} bytes"
                )
            return attachment.contents.tobytes()
        except Exception as err:
            return format_html(f"cannot preview: {err}")

    def json_contents(self, attachment: PluginAttachment):
        try:
            if attachment.file_size > ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES:
                raise ValueError(
                    f"file size {attachment.file_size} is larger than {ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES} bytes"
                )
            return json.loads(attachment.contents.tobytes())
        except Exception as err:
            return format_html(f"cannot preview: {err}")

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False
