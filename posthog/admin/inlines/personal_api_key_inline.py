from django.contrib import admin

from posthog.models.personal_api_key import PersonalAPIKey


class PersonalAPIKeyInline(admin.TabularInline):
    model = PersonalAPIKey
    extra = 0
    fields = ("label", "mask_value", "created_at", "last_used_at", "scopes")
    readonly_fields = ("label", "mask_value", "created_at", "last_used_at", "scopes")
    can_delete = False
    show_change_link = True
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        # Prevent adding API keys through the admin (they should be created via API)
        return False

    def has_change_permission(self, request, obj=None):
        # Make the inline completely read-only to prevent formset validation issues
        return False

    def has_view_permission(self, request, obj=None):
        # Ensure the inline is still visible even though change permission is False
        return True
