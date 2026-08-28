from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from posthog.admin.admins.api_key_roll_mixin import RollApiKeyAdminMixin
from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.models import PersonalAPIKey
from posthog.tasks.email import send_personal_api_key_exposed


@admin.register(PersonalAPIKey)
class PersonalAPIKeyAdmin(RollApiKeyAdminMixin):
    roll_success_message = "Personal API key rolled and user notified."

    fields = (
        "id",
        "user",
        "label",
        "created_at",
        "last_used_at",
        "last_rolled_at",
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

    def roll_and_notify(self, key: PersonalAPIKey, more_info: str) -> None:
        old_mask_value = key.mask_value
        serializer = PersonalAPIKeySerializer(instance=key)
        serializer.roll(key)
        send_personal_api_key_exposed(key.user_id, key.id, old_mask_value, more_info)
