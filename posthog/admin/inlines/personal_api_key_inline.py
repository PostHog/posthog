from django.contrib import admin

from posthog.models.personal_api_key import PersonalAPIKey


class PersonalAPIKeyInline(admin.TabularInline):
    model = PersonalAPIKey
    extra = 0
    fields = ("label", "mask_value", "created_at", "last_used_at", "scopes")
    readonly_fields = ("label", "mask_value", "created_at", "last_used_at", "scopes")
    can_delete = True
    show_change_link = True
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        # Prevent adding API keys through the admin (they should be created via API)
        return False
