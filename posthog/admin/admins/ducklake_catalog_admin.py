from django.contrib import admin


class DuckLakeCatalogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "db_host",
        "db_database",
        "bucket",
        "bucket_region",
        "cross_account_role_arn",
        "created_at",
        "updated_at",
    )
    list_filter = ("bucket_region",)
    search_fields = ("=team__id", "db_host", "bucket", "cross_account_role_arn")
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
            "Cross-account S3 access",
            {
                "fields": ("cross_account_role_arn", "cross_account_external_id"),
                "description": "Required settings for writing to customer-owned S3 buckets via IAM role assumption",
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
