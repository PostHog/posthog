from django.contrib import admin

from posthog.models import DuckgresServerTeam


@admin.register(DuckgresServerTeam)
class DuckgresServerTeamAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "server_id",
        "team_id",
        "created_at",
        "updated_at",
    )
    search_fields = ("=team__id", "=server__id")
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("server", "team")

    fieldsets = (
        (
            None,
            {
                "fields": ("id", "server", "team"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
