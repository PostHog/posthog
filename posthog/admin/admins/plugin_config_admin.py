from django.contrib import admin
from django.utils.html import format_html

from posthog.admin.inlines.plugin_attachment_inline import PluginAttachmentInline
from posthog.models import PluginConfig


class PluginConfigAdmin(admin.ModelAdmin):
    list_select_related = ("plugin", "team")
    list_display = ("id", "plugin_name", "team_name", "enabled")
    list_display_links = ("id", "plugin_name")
    list_filter = (
        ("enabled", admin.BooleanFieldListFilter),
        ("deleted", admin.BooleanFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
        ("plugin", admin.RelatedOnlyFieldListFilter),
        "plugin__is_global",
    )
    list_select_related = ("team", "plugin")
    search_fields = ("team__name", "team__organization__name", "plugin__name")
    ordering = ("-created_at",)
    inlines = [PluginAttachmentInline]

    def plugin_name(self, config: PluginConfig):
        return format_html(f"{config.plugin.name} ({config.plugin_id})")

    def team_name(self, config: PluginConfig):
        return format_html(f"{config.team.name} ({config.team_id})")
