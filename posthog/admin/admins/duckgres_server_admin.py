from django.contrib import admin


class DuckgresServerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "host",
        "port",
        "flight_port",
        "database",
        "created_at",
        "updated_at",
    )
    search_fields = ("=team__id", "host")
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("team",)

    fieldsets = (
        (
            None,
            {
                "fields": ("id", "team"),
            },
        ),
        (
            "Connection",
            {
                "fields": ("host", "port", "flight_port", "database", "username", "password"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
