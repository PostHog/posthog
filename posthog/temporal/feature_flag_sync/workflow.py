import json
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone as django_timezone

import structlog
import temporalio.common
import temporalio.activity
import temporalio.workflow

from posthog.clickhouse.client import sync_execute
from posthog.exceptions_capture import capture_exception
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.redis import get_client
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.feature_flag_sync.metrics import (
    get_feature_flag_sync_duration_metric,
    get_feature_flag_sync_events_processed_metric,
    get_feature_flag_sync_finished_metric,
    get_feature_flag_sync_flags_updated_metric,
)

logger = structlog.get_logger(__name__)

FEATURE_FLAG_LAST_CALLED_SYNC_KEY = "posthog:feature_flag_last_called_sync:last_timestamp"


@dataclass
class SyncFeatureFlagLastCalledInputs:
    """Inputs for syncing feature flag last_called_at timestamps."""

    # Could add parameters like batch_size, lookback_hours etc. in the future
    pass


@dataclass
class FlagSyncResult:
    """Result of syncing feature flag timestamps."""

    updated_count: int
    processed_events: int
    sync_duration_seconds: float


@temporalio.activity.defn
def sync_feature_flag_last_called_activity(inputs: SyncFeatureFlagLastCalledInputs) -> FlagSyncResult:
    """
    Sync last_called_at timestamps from ClickHouse $feature_flag_called events to PostgreSQL.

    This activity:
    1. Gets the last sync timestamp from Redis
    2. Queries ClickHouse for flag usage since last sync
    3. Bulk updates PostgreSQL with latest timestamps
    4. Updates the sync checkpoint in Redis
    """
    start_time = django_timezone.now()

    try:
        redis_client = get_client()

        # Get last sync timestamp (default to 24 hours ago for first run)
        try:
            last_sync_str = redis_client.get(FEATURE_FLAG_LAST_CALLED_SYNC_KEY)
            if last_sync_str:
                last_sync_timestamp = django_timezone.datetime.fromisoformat(last_sync_str.decode())
            else:
                last_sync_timestamp = django_timezone.now() - timedelta(days=1)
        except Exception as e:
            logger.warning("Failed to get or parse last sync timestamp", error=str(e))
            last_sync_timestamp = django_timezone.now() - timedelta(days=1)

        current_sync_timestamp = django_timezone.now()

        logger.info(
            "Starting feature flag sync",
            last_sync_timestamp=last_sync_timestamp.isoformat(),
            current_sync_timestamp=current_sync_timestamp.isoformat(),
        )

        # Query ClickHouse for flag usage since last sync
        # Limit 100000 for insurance against large datasets and memory issues during a surge
        result = sync_execute(
            """
            SELECT
                team_id,
                JSONExtractString(properties, '$feature_flag') as flag_key,
                max(timestamp) as last_called_at,
                count() as call_count
            FROM events
            PREWHERE event = '$feature_flag_called'
            WHERE timestamp > %(last_sync_timestamp)s
              AND timestamp <= %(current_sync_timestamp)s
              AND JSONExtractString(properties, '$feature_flag') != ''
            GROUP BY team_id, flag_key
            ORDER BY last_called_at DESC
            LIMIT 100000
            """,
            {
                "last_sync_timestamp": last_sync_timestamp,
                "current_sync_timestamp": current_sync_timestamp,
            },
        )

        if not result:
            # Update checkpoint even if no results
            redis_client.set(FEATURE_FLAG_LAST_CALLED_SYNC_KEY, current_sync_timestamp.isoformat())

            duration = (django_timezone.now() - start_time).total_seconds()

            # Emit metrics for successful completion with no events
            get_feature_flag_sync_finished_metric("completed").add(1)
            get_feature_flag_sync_duration_metric().record(int(duration * 1000))
            get_feature_flag_sync_events_processed_metric().add(0)
            get_feature_flag_sync_flags_updated_metric().add(0)

            return FlagSyncResult(updated_count=0, processed_events=0, sync_duration_seconds=duration)

        # Collect flags for bulk update
        flags_to_update = []
        total_events = sum(row[3] for row in result)  # Sum all call counts

        # Build lookup map of (team_id, key) -> timestamp from ClickHouse results
        flag_updates = {(row[0], row[1]): row[2] for row in result}

        # Batch fetch all relevant flags in a single query
        team_ids = list({row[0] for row in result})
        flag_keys = list({row[1] for row in result})

        flags = FeatureFlag.objects.filter(team_id__in=team_ids, key__in=flag_keys)

        for flag in flags:
            new_timestamp = flag_updates.get((flag.team_id, flag.key))
            if new_timestamp and (flag.last_called_at is None or flag.last_called_at < new_timestamp):
                flag.last_called_at = new_timestamp
                flags_to_update.append(flag)

        # Perform bulk update for better performance
        updated_count = 0
        if flags_to_update:
            try:
                FeatureFlag.objects.bulk_update(flags_to_update, ["last_called_at"], batch_size=1000)
                updated_count = len(flags_to_update)
            except Exception as e:
                capture_exception(e, extra={"flags_count": len(flags_to_update)})

        # Store checkpoint for next sync
        redis_client.set(FEATURE_FLAG_LAST_CALLED_SYNC_KEY, current_sync_timestamp.isoformat())

        duration = (django_timezone.now() - start_time).total_seconds()

        logger.info(
            "Feature flag sync completed",
            updated_count=updated_count,
            processed_events=total_events,
            clickhouse_results=len(result),
            duration_seconds=duration,
        )

        # Emit metrics for successful completion
        get_feature_flag_sync_finished_metric("completed").add(1)
        get_feature_flag_sync_duration_metric().record(int(duration * 1000))
        get_feature_flag_sync_events_processed_metric().add(total_events)
        get_feature_flag_sync_flags_updated_metric().add(updated_count)

        return FlagSyncResult(
            updated_count=updated_count, processed_events=total_events, sync_duration_seconds=duration
        )

    except Exception as e:
        # Emit metrics for failed completion
        get_feature_flag_sync_finished_metric("failed").add(1)
        duration = (django_timezone.now() - start_time).total_seconds()
        get_feature_flag_sync_duration_metric().record(int(duration * 1000))

        capture_exception(e)
        raise


@temporalio.workflow.defn(name="feature-flag-sync")
class SyncFeatureFlagLastCalledWorkflow(PostHogWorkflow):
    """Workflow for syncing feature flag last_called_at timestamps from ClickHouse to PostgreSQL."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SyncFeatureFlagLastCalledInputs:
        """Parse inputs from the management command CLI."""
        if inputs:
            loaded = json.loads(inputs[0])
            return SyncFeatureFlagLastCalledInputs(**loaded)
        return SyncFeatureFlagLastCalledInputs()

    @temporalio.workflow.run
    async def run(self, inputs: SyncFeatureFlagLastCalledInputs | None = None) -> FlagSyncResult:
        """
        Main workflow execution.

        This workflow syncs feature flag last_called_at timestamps by:
        1. Running the sync activity with retry policy
        2. Returning the sync results for observability
        """
        if inputs is None:
            inputs = SyncFeatureFlagLastCalledInputs()

        result = await temporalio.workflow.execute_activity(
            sync_feature_flag_last_called_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),  # Generous timeout for large datasets
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=timedelta(seconds=30),
                maximum_attempts=3,
                maximum_interval=timedelta(minutes=2),
            ),
        )

        return result
