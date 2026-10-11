from django.db.models import TextChoices

from rest_framework import serializers


class DashboardSharingRefreshType(TextChoices):
    BLOCKING = "blocking", "Use fresh cached results"
    FORCE_BLOCKING = "force_blocking", "Recalculate"


class DashboardQuerySharingParamsSerializer(serializers.Serializer):
    tile_ids = serializers.CharField(max_length=512, help_text="Comma-separated insight tile IDs, at most 32.")
    client_query_id = serializers.UUIDField(help_text="Cancellation ID for this dashboard refresh batch.")
    refresh = serializers.ChoiceField(
        choices=DashboardSharingRefreshType.choices,
        help_text="Use fresh cached results (blocking), or recalculate (force_blocking).",
    )

    def validate_tile_ids(self, value: str) -> list[int]:
        try:
            ids = [int(item) for item in value.split(",")]
        except ValueError:
            raise serializers.ValidationError("Expected comma-separated tile IDs.")
        if not 1 <= len(ids) <= 32 or len(set(ids)) != len(ids) or any(item < 1 for item in ids):
            raise serializers.ValidationError("Supply between 1 and 32 distinct positive tile IDs.")
        return ids
