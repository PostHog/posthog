from django.contrib import admin
from django.utils.html import format_html

from posthog.models import Plugin


class PluginAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "organization_id", "is_global")
    list_display_links = ("id", "name")
    list_filter = ("plugin_type", "is_global")
    autocomplete_fields = ("organization",)
    search_fields = ("name",)
    ordering = ("-created_at",)

    readonly_fields = ["id", "organization", "created_at", "updated_at", "is_stateless"]

    fieldsets = [
        (
            None,
            {
                "fields": ["id", "organization", "created_at", "updated_at"],
            },
        ),
        (
            "Configuration",
            {
                "fields": ["is_global", "is_preinstalled", "is_stateless", "log_level"],
            },
        ),
        (
            "Metadata",
            {
                "fields": ["name", "description", "plugin_type", "url", "icon", "config_schema", "capabilities"],
            },
        ),
        (
            "Git update checks",
            {
                "classes": ["collapse"],
                "fields": ["tag", "latest_tag", "latest_tag_checked_at"],
            },
        ),
        (
            "Deprecated metadata",
            {
                "classes": ["collapse"],
                "fields": ["error", "from_json", "from_web", "source", "metrics", "public_jobs"],
            },
        ),
        # Not used for now and very slow to load
        # (
        #     "Access control",
        #     {
        #         "fields": ["has_private_access"],
        #     },
        # ),
    ]

    def organization_link(self, plugin: Plugin):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            plugin.organization.pk,
            plugin.organization.name,
        )
