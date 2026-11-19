from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from posthog.admin.console.moved import MovedToConsole
from posthog.models import PersonalAPIKey


@admin.register(PersonalAPIKey)
class PersonalAPIKeyAdmin(admin.ModelAdmin):
    fields = (
        "id",
        "user",
        "label",
        "created_at",
        "last_used_at",
        "last_rolled_at",
        "expires_at",
        "scopes",
        "scoped_teams",
        "scoped_organizations",
        "team",
        "roll_action",
    )
    readonly_fields = (
        "id",
        "team",
        "user",
        "roll_action",
    )
    list_display = ("id", "label", "mask_value", "user_link", "created_at", "last_used_at", "scopes")
    list_display_links = ("id", "label")
    list_select_related = ("user",)
    search_fields = ("id", "user__email", "scopes")
    autocomplete_fields = ("user", "team")
    ordering = ("-created_at",)

    @admin.display(description="User")
    def user_link(self, key: PersonalAPIKey) -> SafeString:
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_user_change", args=[key.user.pk]),
            key.user.email,
        )

    @admin.display(description="Roll key")
    def roll_action(self, key: PersonalAPIKey) -> str | SafeString:
        if not key.pk:
            return ""
        return MovedToConsole.action("user", key.user, "personal-api-keys", "Rolling an exposed key")
