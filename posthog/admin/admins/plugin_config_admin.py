from django.contrib import admin
from django.utils.html import format_html

from posthog.admin.inlines.plugin_attachment_inline import PluginAttachmentInline
from posthog.models import PluginConfig


class PluginConfigAdmin(admin.ModelAdmin):
    list_select_related = ("plugin", "team")
    list_display = ("id", "plugin_name", "team_name", "enabled", "deleted")
    list_display_links = ("id", "plugin_name")
    list_filter = (
        ("enabled", admin.BooleanFieldListFilter),
        ("deleted", admin.BooleanFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
        ("plugin", admin.RelatedOnlyFieldListFilter),
        "plugin__is_global",
    )
    search_fields = ("team__name", "team__organization__name", "plugin__name")
    ordering = ("-created_at",)

    inlines = [PluginAttachmentInline]
    readonly_fields = [
        "id",
        "plugin",
        "team",
        "created_at",
        "updated_at",
    ]

    fieldsets = [
        (
            None,
            {
                "fields": ["id", "plugin", "team", "created_at", "updated_at"],
            },
        ),
        (
            "Common config",
            {
                "fields": ["enabled", "deleted", "order", "config"],
            },
        ),
        (
            "CDP (work in progress)",
            {
                "classes": ["collapse"],
                "fields": ["filters"],
            },
        ),
        (
            "Frontend apps",
            {
                "classes": ["collapse"],
                "fields": ["name", "description", "web_token"],
            },
        ),
    ]

    def plugin_name(self, config: PluginConfig):
        return format_html("{} ({})", config.plugin.name, config.plugin_id)

    def team_name(self, config: PluginConfig):
        return format_html("{} ({})", config.team.name, config.team_id)
