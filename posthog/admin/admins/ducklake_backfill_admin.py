from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from posthog.models import DuckLakeBackfill


@admin.register(DuckLakeBackfill)
class DuckLakeBackfillAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "enabled",
        "table_suffix",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_filter = ("enabled",)
    search_fields = ("=team__id", "table_suffix")
    # `table_suffix` is write-once: it names a team's warehouse tables/schema, so changing it after
    # data is written moves the target and orphans the old tables. It's set only through the
    # validated enable flow (`enable_team_backfill`), never edited here.
    readonly_fields = ("id", "table_suffix", "created_at", "updated_at")
    raw_id_fields = ("team", "created_by")
    actions = ("make_enabled", "make_disabled")

    # Toggling `enabled` drives the duckling sensors into expensive ClickHouse->S3
    # backfills, so it goes through Django's action-confirmation flow rather than an
    # inline `list_editable` checkbox that can be flipped for the wrong team in passing.
    @admin.action(description="Enable warehouse backfills for selected teams")
    def make_enabled(self, request: HttpRequest, queryset: QuerySet[DuckLakeBackfill]) -> None:
        updated = queryset.update(enabled=True)
        self.message_user(request, f"Enabled warehouse backfills for {updated} team(s).")

    @admin.action(description="Disable warehouse backfills for selected teams")
    def make_disabled(self, request: HttpRequest, queryset: QuerySet[DuckLakeBackfill]) -> None:
        updated = queryset.update(enabled=False)
        self.message_user(request, f"Disabled warehouse backfills for {updated} team(s).")

    fieldsets = (
        (
            None,
            {
                "fields": ("id", "team", "enabled", "table_suffix"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_by", "created_at", "updated_at"),
            },
        ),
    )
