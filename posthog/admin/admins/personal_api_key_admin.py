from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from posthog.models import PersonalAPIKey


class PersonalAPIKeyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "label",
        "mask_value",
        "user_link",
        "created_at",
        "last_used_at",
        "scopes",
    )
    list_display_links = ("id", "label")
    list_select_related = ("user",)
    search_fields = ("id", "user__email", "scopes")
    autocomplete_fields = ("user",)
    ordering = ("-created_at",)

    @admin.display(description="User")
    def user_link(self, key: PersonalAPIKey):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_user_change", args=[key.user.pk]),
            key.user.email,
        )
