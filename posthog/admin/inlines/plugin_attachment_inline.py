import json

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from posthog.models import PluginAttachment

ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES = 1024 * 1024


class PluginAttachmentInline(admin.StackedInline):
    extra = 0
    model = PluginAttachment
    fields = ("key", "content_type", "file_size", "raw_contents", "parsed_json")
    readonly_fields = fields

    def raw_contents(self, attachment: PluginAttachment):
        try:
            if attachment.file_size > ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES:
                raise ValueError(
                    f"file size {attachment.file_size} is larger than {ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES} bytes"
                )
            return attachment.contents
        except Exception as err:
            return format_html(f"cannot preview: {err}")

    def parsed_json(self, attachment: PluginAttachment):
        try:
            if attachment.file_size > ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES:
                raise ValueError(
                    f"file size {attachment.file_size} is larger than {ATTACHMENT_PREVIEW_SIZE_LIMIT_BYTES} bytes"
                )

            response = json.dumps(json.loads(attachment.contents), sort_keys=True, indent=4)
            return mark_safe(f"<pre>{response}</pre>")
        except Exception as err:
            return format_html(f"cannot preview: {err}")

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False
