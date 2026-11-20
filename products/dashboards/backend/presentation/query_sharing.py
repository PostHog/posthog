from django.db.models import TextChoices

from rest_framework import serializers

from products.dashboards.backend.facade.query_sharing import MAX_CACHED_TILES_BATCH_SIZE, DashboardSharingOutcome


class DashboardSharingRefreshType(TextChoices):
    BLOCKING = "blocking", "Use fresh cached results"
    FORCE_BLOCKING = "force_blocking", "Recalculate"


class DashboardQuerySharingParamsSerializer(serializers.Serializer):
    debug = serializers.BooleanField(
        default=False,
        help_text="Include request-local sharing decisions and measured ClickHouse work in tile events.",
    )
    tile_ids = serializers.CharField(
        max_length=1024,
        help_text=f"Comma-separated insight tile IDs, at most {MAX_CACHED_TILES_BATCH_SIZE}. Visible tiles first: tiles compute in this order.",
    )
    client_query_id = serializers.UUIDField(help_text="Cancellation ID for this dashboard refresh batch.")
    refresh = serializers.ChoiceField(
        choices=DashboardSharingRefreshType.choices,
        help_text="Use fresh cached results (blocking), or recalculate (force_blocking).",
    )
    cached_first = serializers.BooleanField(
        default=False,
        help_text=(
            "Send every tile's cached result in one `cached` event first, stale results included and marked. "
            "Then compute only the tiles whose result is missing or stale, or every tile with force_blocking."
        ),
    )

    def validate_tile_ids(self, value: str) -> list[int]:
        try:
            ids = [int(item) for item in value.split(",")]
        except ValueError:
            raise serializers.ValidationError("Expected comma-separated tile IDs.")
        if (
            not 1 <= len(ids) <= MAX_CACHED_TILES_BATCH_SIZE
            or len(set(ids)) != len(ids)
            or any(item < 1 for item in ids)
        ):
            raise serializers.ValidationError(
                f"Supply between 1 and {MAX_CACHED_TILES_BATCH_SIZE} distinct positive tile IDs."
            )
        return ids


class DashboardSharingExecutionDebugSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=DashboardSharingOutcome.choices, help_text="Execution sharing outcome.")
    tile_ids = serializers.ListField(
        child=serializers.IntegerField(), help_text="Tiles participating in this execution."
    )
    rule = serializers.CharField(allow_blank=True, help_text="Sharing rule, or empty for separate execution.")
    reason = serializers.CharField(allow_blank=True, help_text="Why the query ran separately or fell back.")


class DashboardSharingDebugSerializer(serializers.Serializer):
    executions = DashboardSharingExecutionDebugSerializer(
        many=True, help_text="Decisions recorded by this tile's worker."
    )
    truncated = serializers.BooleanField(help_text="Whether the per-worker limit of 64 diagnostic records was reached.")
    query_count = serializers.IntegerField(help_text="ClickHouse queries measured by this worker, including lookups.")
    rows_read = serializers.IntegerField(help_text="ClickHouse rows read, attributed once to the executing worker.")
    duration_ms = serializers.FloatField(
        help_text="Summed ClickHouse execution time in milliseconds; client round-trip time on older protocols."
    )
