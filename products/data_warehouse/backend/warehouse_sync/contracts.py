from dataclasses import dataclass
from datetime import datetime

from rest_framework import serializers

WAREHOUSE_SYNC_STATES = ["caught_up", "lagging", "error", "not_started"]


@dataclass
class SyncError:
    message: str
    since: datetime


@dataclass
class WarehouseSyncStatusDTO:
    state: str
    fresh_through: datetime | None
    lag_seconds: int | None
    last_activity_at: datetime | None
    error: SyncError | None
    updated_at: datetime


class _SyncErrorSerializer(serializers.Serializer[SyncError]):  # type: ignore[type-arg]  # DRF Serializer isn't generic at runtime
    message = serializers.CharField(help_text="Human-readable error message.")
    since = serializers.DateTimeField(help_text="When the current error first occurred.")


class WarehouseSyncStatusSerializer(serializers.Serializer[WarehouseSyncStatusDTO]):  # type: ignore[type-arg]  # DRF Serializer isn't generic at runtime
    state = serializers.ChoiceField(choices=WAREHOUSE_SYNC_STATES, help_text="Overall freshness state.")
    fresh_through = serializers.DateTimeField(
        allow_null=True, help_text="Timestamp the warehouse is fresh through for this project, or null if no data yet."
    )
    lag_seconds = serializers.IntegerField(allow_null=True, help_text="Seconds behind now, or null if unknown.")
    last_activity_at = serializers.DateTimeField(allow_null=True, help_text="Last time the backfill made progress.")
    error = _SyncErrorSerializer(allow_null=True, help_text="Current error, or null when healthy.")
    updated_at = serializers.DateTimeField(help_text="When this status was computed.")
