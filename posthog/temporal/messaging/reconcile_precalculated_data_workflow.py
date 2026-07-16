import os
import time
import asyncio
import datetime as dt
import dataclasses
from typing import Any, Optional

import temporalio.common
import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.backfill_precalculated_events_workflow import flush_kafka_batch_async

from products.cohorts.backend.models.cohort import Cohort, CohortType

LOGGER = get_logger(__name__)

# precalculated_events stores the person_id that was resolved for a distinct_id when the row
# was written. When a later identify/merge re-points the distinct_id to another person, the
# row silently goes stale: cohort_membership keeps a person the distinct_id no longer belongs
# to and misses the surviving one. The cohort calculation path deliberately never joins
# person tables, so the correction has to happen against the stored rows instead: this
# workflow diffs precalculated_events against person_distinct_id_overrides (the record of
# post-ingestion mapping changes) and re-emits corrected rows through the same Kafka topic
# the realtime consumer and backfill use. ReplacingMergeTree keys the table on
# (team_id, condition, date, distinct_id, uuid) with _timestamp as version, so a re-emitted
# row replaces the stale one. cohort_membership then self-heals on the next calculation run,
# whose FULL OUTER JOIN diff emits 'left' for the old person and 'entered' for the new one.
#
# The override row written at merge time is the invalidation signal: each scheduled run
# picks up distinct_ids whose override landed within the lookback window
# (RECONCILE_EVENTS_OVERRIDES_LOOKBACK_HOURS) and repairs just their rows, so the schedule
# can run at the realtime calculation cadence and a merge is reconciled by the next
# calculation run instead of hours later. A `full_scan` input ignores the window — use it
# for first-deploy remediation or after the workflow was down longer than the lookback.
#
# Timing constraints: the lookback must comfortably exceed the schedule interval (so no
# merge falls between runs), and both must stay well inside the person-overrides squash
# cadence (SQUASH_PERSON_OVERRIDES_SCHEDULE, weekly by default) — the squash folds
# overrides into the events table and then DELETES the override rows, and
# precalculated_events is not part of that squash, so any override this workflow never saw
# becomes unrepairable except by an event backfill re-run.

# Latest surviving mapping per overridden distinct_id; mirrors the HogQL
# person_distinct_id_overrides lazy table (argmax_select with deleted_field="is_deleted").
OVERRIDES_QUERY = """
    SELECT
        distinct_id,
        argMax(person_id, version) AS person_id
    FROM person_distinct_id_overrides
    WHERE team_id = %(team_id)s
    GROUP BY distinct_id
    HAVING argMax(is_deleted, version) = 0
    FORMAT JSONEachRow
"""

# Incremental variant: only distinct_ids whose latest override landed inside the lookback
# window. max(_timestamp) (not argMax) so a re-merge of an old distinct_id re-qualifies it.
RECENT_OVERRIDES_QUERY = """
    SELECT
        distinct_id,
        argMax(person_id, version) AS person_id
    FROM person_distinct_id_overrides
    WHERE team_id = %(team_id)s
    GROUP BY distinct_id
    HAVING argMax(is_deleted, version) = 0 AND max(_timestamp) >= toDateTime(%(since)s)
    FORMAT JSONEachRow
"""

# Latest version of each precalculated_events row for a batch of overridden distinct_ids.
# GROUP BY covers the full ReplacingMergeTree sort key (minus the constant team_id) with
# argMax by _timestamp, so rows already corrected in an earlier pass — but not yet collapsed
# by a background merge — don't get re-emitted forever.
PRECALCULATED_EVENTS_BATCH_QUERY = """
    SELECT
        condition,
        date,
        distinct_id,
        uuid,
        argMax(person_id, _timestamp) AS person_id,
        argMax(source, _timestamp) AS source
    FROM precalculated_events
    WHERE team_id = %(team_id)s
      AND distinct_id IN %(distinct_ids)s
    GROUP BY condition, date, distinct_id, uuid
    FORMAT JSONEachRow
"""


@dataclasses.dataclass
class ReconcilePrecalculatedEventsWorkflowInputs:
    """Inputs for the reconciliation workflow."""

    # Manual override for targeted runs; None reconciles every team with realtime cohorts.
    team_ids: Optional[list[int]] = None
    # Ignore the overrides lookback window and diff against every override still in the
    # table. For remediation runs and recovery after downtime longer than the lookback.
    full_scan: bool = False

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_ids": self.team_ids, "full_scan": self.full_scan}


@dataclasses.dataclass
class ReconcileTeamInputs:
    """Inputs for reconciling a single team."""

    team_id: int
    full_scan: bool = False

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "full_scan": self.full_scan}


@dataclasses.dataclass
class ReconciliationTeamIdsResult:
    """Teams that have realtime cohorts and therefore precalculated_events rows to check."""

    team_ids: list[int]


@dataclasses.dataclass
class ReconcileTeamResult:
    """Result from reconciling one team's precalculated_events."""

    overridden_distinct_ids: int
    rows_checked: int
    rows_corrected: int
    duration_seconds: float


@temporalio.activity.defn
async def get_reconciliation_team_ids_activity() -> ReconciliationTeamIdsResult:
    """Return the teams whose precalculated_events need reconciling.

    Only teams with realtime cohorts feed the realtime calculation path, so only their rows
    can affect cohort_membership.
    """

    @database_sync_to_async
    def get_team_ids() -> list[int]:
        return list(
            Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME)
            .values_list("team_id", flat=True)
            .distinct()
            .order_by("team_id")
        )

    return ReconciliationTeamIdsResult(team_ids=await get_team_ids())


@temporalio.activity.defn
async def reconcile_team_precalculated_events_activity(inputs: ReconcileTeamInputs) -> ReconcileTeamResult:
    """Re-emit precalculated_events rows whose person_id no longer matches the current mapping."""
    bind_contextvars()
    logger = LOGGER.bind(team_id=inputs.team_id)
    start_time = time.time()

    try:
        distinct_id_batch_size = int(os.environ.get("RECONCILE_EVENTS_DISTINCT_ID_BATCH_SIZE", "1000"))
    except ValueError:
        logger.warning("Invalid RECONCILE_EVENTS_DISTINCT_ID_BATCH_SIZE, using default 1000")
        distinct_id_batch_size = 1000
    try:
        kafka_flush_batch_size = int(os.environ.get("RECONCILE_EVENTS_KAFKA_FLUSH_BATCH_SIZE", "1000"))
    except ValueError:
        logger.warning("Invalid RECONCILE_EVENTS_KAFKA_FLUSH_BATCH_SIZE, using default 1000")
        kafka_flush_batch_size = 1000
    try:
        overrides_lookback_hours = int(os.environ.get("RECONCILE_EVENTS_OVERRIDES_LOOKBACK_HOURS", "48"))
    except ValueError:
        logger.warning("Invalid RECONCILE_EVENTS_OVERRIDES_LOOKBACK_HOURS, using default 48")
        overrides_lookback_hours = 48

    if inputs.full_scan:
        overrides_query = OVERRIDES_QUERY
        overrides_params: dict[str, Any] = {"team_id": inputs.team_id}
    else:
        since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=overrides_lookback_hours)
        overrides_query = RECENT_OVERRIDES_QUERY
        overrides_params = {"team_id": inputs.team_id, "since": since.strftime("%Y-%m-%d %H:%M:%S")}

    async with Heartbeater(details=(f"Loading person overrides for team {inputs.team_id}",)) as heartbeater:
        with tags_context(
            team_id=inputs.team_id,
            feature=Feature.BEHAVIORAL_COHORTS,
            product=Product.MESSAGING,
            query_type="precalculated_events_reconciliation",
        ):
            async with get_client(team_id=inputs.team_id) as client:
                # Step 1: current mapping for each distinct_id merged within the lookback
                # window (or every overridden one, on a full scan). The squash job keeps
                # the overrides table small, so this fits in memory per team.
                overrides: dict[str, str] = {}
                async for row in client.stream_query_as_jsonl(overrides_query, query_parameters=overrides_params):
                    overrides[str(row["distinct_id"])] = str(row["person_id"])

                if not overrides:
                    return ReconcileTeamResult(
                        overridden_distinct_ids=0,
                        rows_checked=0,
                        rows_corrected=0,
                        duration_seconds=time.time() - start_time,
                    )

                logger.info(f"Checking precalculated_events against {len(overrides)} overridden distinct_ids")

                # Step 2: scan this team's precalculated_events for those distinct_ids in
                # batches and re-emit any row still carrying a superseded person_id.
                kafka_producer = get_producer(topic=KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS)
                kafka_results: list = []
                rows_checked = 0
                rows_corrected = 0

                overridden_distinct_ids = list(overrides.keys())
                for batch_start in range(0, len(overridden_distinct_ids), distinct_id_batch_size):
                    batch = overridden_distinct_ids[batch_start : batch_start + distinct_id_batch_size]

                    async for row in client.stream_query_as_jsonl(
                        PRECALCULATED_EVENTS_BATCH_QUERY,
                        query_parameters={"team_id": inputs.team_id, "distinct_ids": batch},
                    ):
                        rows_checked += 1
                        distinct_id = str(row["distinct_id"])
                        current_person_id = overrides[distinct_id]
                        if str(row["person_id"]) == current_person_id:
                            continue

                        # Preserve the original source: the backfill coordinator's
                        # day-already-backfilled check filters on it, so rewriting it here
                        # would make backfilled days look uncovered.
                        produce_result = await asyncio.to_thread(
                            kafka_producer.produce,
                            topic=KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
                            data={
                                "uuid": str(row["uuid"]),
                                "team_id": inputs.team_id,
                                "person_id": current_person_id,
                                "distinct_id": distinct_id,
                                "condition": str(row["condition"]),
                                "date": str(row["date"]),
                                "source": str(row["source"]),
                            },
                        )
                        kafka_results.append(produce_result)
                        rows_corrected += 1

                        if len(kafka_results) >= kafka_flush_batch_size:
                            await flush_kafka_batch_async(kafka_results, kafka_producer, inputs.team_id, logger)
                            kafka_results.clear()

                    heartbeater.details = (
                        f"Checked {rows_checked} rows, corrected {rows_corrected} "
                        f"({batch_start + len(batch)}/{len(overridden_distinct_ids)} distinct_ids)",
                    )

                if kafka_results:
                    await flush_kafka_batch_async(kafka_results, kafka_producer, inputs.team_id, logger)

    duration_seconds = time.time() - start_time
    logger.info(
        f"Reconciled precalculated_events for team {inputs.team_id}: checked {rows_checked} rows, "
        f"corrected {rows_corrected} in {duration_seconds:.1f}s",
        overridden_distinct_ids=len(overrides),
        rows_checked=rows_checked,
        rows_corrected=rows_corrected,
    )

    return ReconcileTeamResult(
        overridden_distinct_ids=len(overrides),
        rows_checked=rows_checked,
        rows_corrected=rows_corrected,
        duration_seconds=duration_seconds,
    )


@temporalio.workflow.defn(name="reconcile-precalculated-events")
class ReconcilePrecalculatedEventsWorkflow(PostHogWorkflow):
    """Scheduled workflow that repairs precalculated_events rows made stale by person merges."""

    # Default JSON parse_inputs, so manual runs can pass {"team_ids": [...], "full_scan": true}.
    inputs_cls = ReconcilePrecalculatedEventsWorkflowInputs
    inputs_optional = True

    @temporalio.workflow.run
    async def run(self, inputs: ReconcilePrecalculatedEventsWorkflowInputs) -> None:
        workflow_logger = temporalio.workflow.logger

        if inputs.team_ids is not None:
            team_ids = inputs.team_ids
        else:
            selection = await temporalio.workflow.execute_activity(
                get_reconciliation_team_ids_activity,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )
            team_ids = selection.team_ids

        if not team_ids:
            workflow_logger.info("No teams with realtime cohorts, nothing to reconcile")
            return

        workflow_logger.info(f"Reconciling precalculated_events for {len(team_ids)} teams")

        failed_teams: list[int] = []
        total_corrected = 0
        for team_id in team_ids:
            try:
                result = await temporalio.workflow.execute_activity(
                    reconcile_team_precalculated_events_activity,
                    ReconcileTeamInputs(team_id=team_id, full_scan=inputs.full_scan),
                    start_to_close_timeout=dt.timedelta(hours=2),
                    heartbeat_timeout=dt.timedelta(minutes=5),
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=dt.timedelta(seconds=10),
                        maximum_interval=dt.timedelta(minutes=1),
                    ),
                )
                total_corrected += result.rows_corrected
            except Exception as e:
                # Keep going: one team's failure shouldn't leave every other team stale.
                failed_teams.append(team_id)
                workflow_logger.exception(f"Reconciliation failed for team {team_id}: {e}")

        workflow_logger.info(
            f"Reconciliation completed: corrected {total_corrected} rows across "
            f"{len(team_ids) - len(failed_teams)}/{len(team_ids)} teams"
            + (f", failed teams: {failed_teams}" if failed_teams else "")
        )
