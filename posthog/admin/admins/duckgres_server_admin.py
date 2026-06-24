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
    # bucket / bucket_region are control-plane-owned: provisioning persists them
    # and status_for() self-heals them on every read, so a manual admin edit
    # would just be overwritten. Show them, but read-only.
    readonly_fields = ("id", "created_at", "updated_at", "bucket", "bucket_region")
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
                # The duckling's per-org S3 bucket. Control-plane-owned and
                # read-only: provisioning persists it and status_for() self-heals
                # it from the warehouse status, so it's shown for reference but not
                # editable here.
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
