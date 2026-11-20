from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.admin.console.moved import MovedToConsole
from posthog.admin.inlines.team_inline import TeamInline
from posthog.admin.organization_members import organization_members_table
from posthog.models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "organization_link",
        "organization_id",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("organization",)
    search_fields = (
        "id",
        "name",
        "organization__id",
        "organization__name",
    )
    autocomplete_fields = ["organization"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "is_pending_deletion",
        "deletion_scheduled_at",
        "deletion_moved",
        "organization_members",
    ]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "name",
                    "organization",
                    "product_description",
                    "is_pending_deletion",
                    "deletion_scheduled_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
        ("Organization members", {"fields": ("organization_members",)}),
        ("Danger zone", {"fields": ("deletion_moved",)}),
    )
    inlines = [TeamInline]

    def organization_link(self, project: Project):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_organization_change", args=[project.organization.pk]),
            project.organization.name,
        )

    @admin.display(description="Deletion")
    def deletion_moved(self, project: Project):
        if not project.pk:
            return "-"
        return MovedToConsole.action("project", project, "deletion", "Deleting the project")

    @admin.display(description="Members")
    def organization_members(self, project: Project):
        if not project.pk:
            return "-"
        return organization_members_table(project.organization_id)
