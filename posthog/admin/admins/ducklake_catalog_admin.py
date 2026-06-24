from django.contrib import admin

from posthog.models import DuckLakeCatalog


@admin.register(DuckLakeCatalog)
class DuckLakeCatalogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "organization_id",
        "db_host",
        "db_database",
        "bucket",
        "bucket_region",
        "created_at",
        "updated_at",
    )
    list_filter = ("bucket_region",)
    search_fields = ("=team__id", "=organization__id", "db_host", "bucket")
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("team", "organization")

    fieldsets = (
        (
            None,
            {
                "fields": ("id", "team", "organization"),
            },
        ),
        (
            "Database connection",
            {
                "fields": ("db_host", "db_port", "db_database", "db_username", "db_password"),
            },
        ),
        (
            "S3 bucket",
            {
                "fields": ("bucket", "bucket_region"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
