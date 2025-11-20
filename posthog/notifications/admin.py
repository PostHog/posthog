from django.contrib import admin

from posthog.models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "team", "resource_type", "priority", "read_at", "created_at")
    list_filter = ("resource_type", "priority", "read_at", "created_at")
    search_fields = ("title", "message", "user__email", "team__name")
    readonly_fields = ("id", "created_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "user",
                    "team",
                    "title",
                    "message",
                )
            },
        ),
        (
            "Resource Info",
            {
                "fields": (
                    "resource_type",
                    "resource_id",
                    "context",
                )
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "priority",
                    "read_at",
                    "created_at",
                )
            },
        ),
    )


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "team", "resource_type", "enabled", "updated_at")
    list_filter = ("resource_type", "enabled", "updated_at")
    search_fields = ("user__email", "team__name", "resource_type")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-updated_at",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "user",
                    "team",
                    "resource_type",
                    "enabled",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
