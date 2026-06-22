from django.contrib import admin

from posthog.models import DuckgresServer


@admin.register(DuckgresServer)
class DuckgresServerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "organization_id",
        "host",
        "port",
        "flight_port",
        "database",
        "bucket",
        "created_at",
        "updated_at",
    )
    search_fields = ("=team__id", "=organization__id", "host", "bucket")
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
            "Connection",
            {
                "fields": ("host", "port", "flight_port", "database", "username", "password"),
            },
        ),
        (
            "Storage",
            {
                # The duckling's per-org S3 bucket. Normally populated automatically
                # from the provision response (the control plane is the authoritative
                # source of the name). Editable here for manual reconciliation of rows
                # provisioned before the CP returned it.
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
