from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from posthog.models import DuckgresServerTeam


@admin.register(DuckgresServerTeam)
class DuckgresServerTeamAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "server_id",
        "team_id",
        "backfill_enabled",
        "table_suffix",
        "earliest_event_date",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_filter = ("backfill_enabled",)
    search_fields = ("=team__id", "=server__id", "table_suffix")
    # `table_suffix` is write-once: it names a team's warehouse tables/schema, so changing it after
    # data is written moves the target and orphans the old tables. It's set only through the
    # validated enable flow (`enable_team_backfill`), never edited here.
    # `earliest_event_date` is the sensor's cached backfill floor — shown for visibility but
    # not hand-edited (the sensor owns it; it resolves+caches it from ClickHouse once). To
    # force re-discovery, use the "Reset earliest_event_date" action rather than a free-form edit.
    readonly_fields = ("id", "table_suffix", "earliest_event_date", "created_at", "updated_at")
    raw_id_fields = ("server", "team", "created_by")
    actions = ("make_enabled", "make_disabled", "reset_earliest_event_date")

    # Toggling `backfill_enabled` drives the duckling sensors into expensive ClickHouse->S3
    # backfills, so it goes through Django's action-confirmation flow rather than an
    # inline `list_editable` checkbox that can be flipped for the wrong team in passing.
    @admin.action(description="Enable warehouse backfills for selected teams")
    def make_enabled(self, request: HttpRequest, queryset: QuerySet[DuckgresServerTeam]) -> None:
        updated = queryset.update(backfill_enabled=True)
        self.message_user(request, f"Enabled warehouse backfills for {updated} team(s).")

    @admin.action(description="Disable warehouse backfills for selected teams")
    def make_disabled(self, request: HttpRequest, queryset: QuerySet[DuckgresServerTeam]) -> None:
        updated = queryset.update(backfill_enabled=False)
        self.message_user(request, f"Disabled warehouse backfills for {updated} team(s).")

    # The field is read-only in the form (the sensor owns it), but a team that previously had
    # no events — and so cached the no-history sentinel — needs a way to re-trigger discovery
    # after a historical import. Clearing it makes the sensor re-query ClickHouse and re-derive
    # the backfill range on its next tick.
    @admin.action(description="Reset earliest_event_date (re-discover backfill range)")
    def reset_earliest_event_date(self, request: HttpRequest, queryset: QuerySet[DuckgresServerTeam]) -> None:
        updated = queryset.update(earliest_event_date=None)
        self.message_user(request, f"Reset backfill range for {updated} team(s); the sensor will re-discover it.")

    fieldsets = (
        (
            None,
            {
                "fields": ("id", "server", "team", "backfill_enabled", "table_suffix"),
            },
        ),
        (
            "Backfill range",
            {
                "fields": ("earliest_event_date",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_by", "created_at", "updated_at"),
            },
        ),
    )
