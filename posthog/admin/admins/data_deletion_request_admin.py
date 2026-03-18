from django.contrib import admin


class DataDeletionRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "request_type",
        "status",
        "events",
        "start_time",
        "end_time",
        "created_by",
        "approved",
        "created_at",
    )
    list_filter = ("request_type", "status", "requires_approval", "approved")
    search_fields = ("team_id", "events", "properties", "notes")
    readonly_fields = ("count", "part_count", "parts_size", "created_at", "updated_at")
    autocomplete_fields = ("created_by", "approved_by")
    ordering = ("-created_at",)
