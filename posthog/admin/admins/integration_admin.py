from django.contrib import admin
from django.utils.html import format_html

from posthog.models.integration import Integration
from posthog.models.organization_integration import OrganizationIntegration


class IntegrationAdmin(admin.ModelAdmin):
    list_select_related = ("team", "created_by")
    list_display = ("id", "kind", "integration_id", "team_link", "created_by", "created_at")
    list_display_links = ("id",)
    list_filter = (
        "kind",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = ("integration_id", "team__name", "team__organization__name", "config")
    ordering = ("-created_at",)
    readonly_fields = ("id", "team", "created_by", "created_at")

    fieldsets = [
        (
            None,
            {
                "fields": ["id", "team", "kind", "integration_id", "created_by", "created_at"],
            },
        ),
        (
            "Config",
            {
                "fields": ["config", "sensitive_config", "errors"],
            },
        ),
    ]

    @admin.display(description="Team")
    def team_link(self, obj: Integration) -> str:
        return format_html("{} ({})", obj.team.name, obj.team_id)


class OrganizationIntegrationAdmin(admin.ModelAdmin):
    list_select_related = ("organization", "created_by")
    list_display = ("id", "kind", "integration_id", "organization_link", "created_by", "created_at")
    list_display_links = ("id",)
    list_filter = (
        "kind",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = ("integration_id", "organization__name", "config")
    ordering = ("-created_at",)
    readonly_fields = ("id", "organization", "created_by", "created_at", "updated_at")

    fieldsets = [
        (
            None,
            {
                "fields": ["id", "organization", "kind", "integration_id", "created_by", "created_at", "updated_at"],
            },
        ),
        (
            "Config",
            {
                "fields": ["config", "sensitive_config"],
            },
        ),
    ]

    def organization_link(self, obj: OrganizationIntegration) -> str:
        return format_html("{} ({})", obj.organization.name, obj.organization_id)

    organization_link.short_description = "Organization"  # type: ignore
