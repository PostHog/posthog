from django.contrib import admin


class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "team", "resource_type", "title", "priority", "read_at", "created_at")
    list_filter = ("resource_type", "priority", "read_at", "created_at")
    search_fields = ("title", "message", "user__email", "team__name")
    readonly_fields = ("id", "created_at")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"


class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "team", "resource_type", "enabled", "created_at", "updated_at")
    list_filter = ("resource_type", "enabled", "created_at")
    search_fields = ("user__email", "team__name", "resource_type")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)
