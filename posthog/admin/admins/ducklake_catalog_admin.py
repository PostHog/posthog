from django.contrib import admin


class DuckLakeCatalogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "s3_bucket",
        "rds_host",
        "created_at",
        "updated_at",
    )
    list_filter = ("s3_region",)
    search_fields = ("team_id", "s3_bucket", "rds_host")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("team",)

    fieldsets = (
        (
            "Team",
            {
                "fields": ("team",),
            },
        ),
        (
            "RDS Catalog",
            {
                "fields": (
                    "rds_host",
                    "rds_port",
                    "rds_database",
                    "rds_username",
                    "rds_password",
                ),
            },
        ),
        (
            "S3 Storage",
            {
                "fields": (
                    "s3_bucket",
                    "s3_region",
                ),
            },
        ),
        (
            "Cross-Account Access",
            {
                "fields": (
                    "cross_account_role_arn",
                    "cross_account_external_id",
                ),
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )
