from django.contrib import admin

from posthog.models import DuckLakeBackfill


@admin.register(DuckLakeBackfill)
class DuckLakeBackfillAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "enabled",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_editable = ("enabled",)
    list_filter = ("enabled",)
    search_fields = ("=team__id",)
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("team", "created_by")

    fieldsets = (
        (
            None,
            {
                "fields": ("id", "team", "enabled"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_by", "created_at", "updated_at"),
            },
        ),
    )
