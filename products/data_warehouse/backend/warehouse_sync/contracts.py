from dataclasses import dataclass
from datetime import datetime

from rest_framework import serializers

# Backend-neutral freshness contract. Today only the Dagster event backfill fills it (backend
# "dagster", initial_backfill null, never "seeding"). The "viaduck" backend, "seeding" state, and
# the initial_backfill block are kept so a future CDC backend — which routes per tenant and tracks
# real seeding progress — can populate them without an API or UI change.
WAREHOUSE_SYNC_STATES = ["seeding", "caught_up", "lagging", "error", "not_started"]
WAREHOUSE_SYNC_BACKENDS = ["dagster", "viaduck"]


@dataclass
class InitialBackfill:
    complete: bool
    progress_pct: int | None


@dataclass
class SyncError:
    message: str
    since: datetime


@dataclass
class WarehouseSyncStatusDTO:
    backend: str
    state: str
    fresh_through: datetime | None
    lag_seconds: int | None
    last_activity_at: datetime | None
    # Null when the backend can't determine one-time-load progress (e.g. the Dagster backfill, whose
    # historical partitions predate this telemetry). The CDC backend reports real seeding progress.
    initial_backfill: InitialBackfill | None
    total_rows_synced: int | None
    error: SyncError | None
    updated_at: datetime


class _InitialBackfillSerializer(serializers.Serializer[InitialBackfill]):  # type: ignore[type-arg]
    complete = serializers.BooleanField(help_text="Whether the one-time historical load has finished.")
    progress_pct = serializers.IntegerField(
        allow_null=True, help_text="Historical load progress, 0-100, or null if unknown."
    )


class _SyncErrorSerializer(serializers.Serializer[SyncError]):  # type: ignore[type-arg]
    message = serializers.CharField(help_text="Human-readable error message.")
    since = serializers.DateTimeField(help_text="When the current error first occurred.")


class WarehouseSyncStatusSerializer(serializers.Serializer[WarehouseSyncStatusDTO]):  # type: ignore[type-arg]
    backend = serializers.ChoiceField(choices=WAREHOUSE_SYNC_BACKENDS, help_text="Pipeline moving the data (internal).")
    state = serializers.ChoiceField(choices=WAREHOUSE_SYNC_STATES, help_text="Overall freshness state.")
    fresh_through = serializers.DateTimeField(allow_null=True, help_text="Timestamp the warehouse is fresh through.")
    lag_seconds = serializers.IntegerField(allow_null=True, help_text="Seconds behind now/source, or null if unknown.")
    last_activity_at = serializers.DateTimeField(allow_null=True, help_text="Last time the pipeline made progress.")
    initial_backfill = _InitialBackfillSerializer(
        allow_null=True, help_text="One-time historical load status, or null if the backend can't determine it."
    )
    total_rows_synced = serializers.IntegerField(
        allow_null=True, help_text="Cumulative events moved into the warehouse."
    )
    error = _SyncErrorSerializer(allow_null=True, help_text="Current error, or null when healthy.")
    updated_at = serializers.DateTimeField(help_text="When this status was computed.")
