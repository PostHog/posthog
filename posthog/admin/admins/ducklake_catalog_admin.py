from django.contrib import admin


class DuckLakeCatalogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "rds_host",
        "rds_database",
        "bucket",
        "bucket_region",
        "created_at",
        "updated_at",
    )
    list_filter = ("bucket_region",)
    search_fields = ("team__id", "rds_host", "bucket")
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
            "RDS connection",
            {
                "fields": ("rds_host", "rds_port", "rds_database", "rds_username", "rds_password"),
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
