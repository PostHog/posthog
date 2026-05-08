from django.contrib import admin

from posthog.models import AsyncDeletion


@admin.register(AsyncDeletion)
class AsyncDeletionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deletion_type",
        "group_type_index",
        "team_id",
        "key",
        "created_by",
        "created_at",
        "delete_verified_at",
    )
    list_filter = ("deletion_type", "delete_verified_at")
    search_fields = ("key",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
