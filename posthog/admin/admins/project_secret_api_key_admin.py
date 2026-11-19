from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from posthog.admin.console.moved import MovedToConsole
from posthog.models import ProjectSecretAPIKey


@admin.register(ProjectSecretAPIKey)
class ProjectSecretAPIKeyAdmin(admin.ModelAdmin):
    fields = (
        "id",
        "label",
        "mask_value",
        "team_link",
        "created_by_link",
        "created_at",
        "last_used_at",
        "last_rolled_at",
        "scopes",
        "roll_action",
    )
    # Everything is read-only: this page exists for lookup, and the roll action lives on the team's console page.
    readonly_fields = fields
    list_display = ("id", "label", "mask_value", "team_link", "created_at", "last_used_at", "scopes")
    list_display_links = ("id", "label")
    search_fields = ("id", "label")
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[ProjectSecretAPIKey]:
        # No select_related("team") — Team is a very wide model; team_link only needs team_id.
        return super().get_queryset(request).select_related("created_by")

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Keys created here would be unusable: the plaintext value is only ever surfaced
        # once through the API's create/roll flow.
        return False

    @admin.display(description="Team")
    def team_link(self, key: ProjectSecretAPIKey) -> SafeString:
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[key.team_id]),
            key.team_id,
        )

    @admin.display(description="Created by")
    def created_by_link(self, key: ProjectSecretAPIKey) -> str | SafeString:
        if key.created_by is None:
            return "-"
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_user_change", args=[key.created_by.pk]),
            key.created_by.email,
        )

    @admin.display(description="Roll key")
    def roll_action(self, key: ProjectSecretAPIKey) -> str | SafeString:
        if not key.pk:
            return ""
        return MovedToConsole.action("team", key.team, "secret-api-keys", "Revoking an exposed key")
