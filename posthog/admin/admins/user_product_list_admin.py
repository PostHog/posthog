from django.contrib import admin


class UserProductListAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "team", "product_path", "reason", "enabled", "updated_at")
    list_display_links = ("id",)
    list_filter = (
        "reason",
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
        "reason",
        "reason_text",
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
                "fields": ["enabled", "reason", "reason_text"],
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

    def has_delete_permission(self, request, obj=None):
        return False
