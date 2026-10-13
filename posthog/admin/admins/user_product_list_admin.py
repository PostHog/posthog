from django.contrib import admin

from posthog.models.file_system.user_product_list import UserProductList


@admin.register(UserProductList)
class UserProductListAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "team", "product_path", "enabled", "updated_at")
    list_display_links = ("id",)
    list_filter = (
        "product_path",
        "enabled",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = ("product_path", "user__email", "team__name")
    ordering = ("-created_at",)
    list_select_related = ("user", "team")

    readonly_fields = [
        "id",
        "user",
        "team",
        "product_path",
        "enabled",
        "created_at",
        "updated_at",
    ]

    fieldsets = [
        (
            None,
            {
                "fields": ["id", "user", "team", "product_path"],
            },
        ),
        (
            "Status",
            {
                "fields": ["enabled"],
            },
        ),
        (
            "Timestamps",
            {
                "fields": ["created_at", "updated_at"],
            },
        ),
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
