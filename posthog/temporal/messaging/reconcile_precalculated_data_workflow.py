import os
import time
import asyncio
import datetime as dt
import dataclasses
from typing import Any, Optional

import structlog
import temporalio.common
import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import (
    KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
    KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
)
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.backfill_precalculated_events_workflow import flush_kafka_batch_async
from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    evaluate_combined_filters_with_fallback_sync,
    parse_person_properties,
)
from posthog.temporal.messaging.filter_storage import combine_filter_bytecodes
from posthog.temporal.messaging.types import PersonPropertyFilter

from products.cohorts.backend.models.cohort import Cohort, CohortType

LOGGER = get_logger(__name__)


def _positive_int_env(name: str, default: int, logger: structlog.BoundLogger) -> int:
    """Parse a positive-int env var, falling back to `default` if unset, malformed, or <= 0.

    A zero/negative batch size breaks range()'s step, and a zero/negative lookback
    places `since` at or after "now", silently excluding every override.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(f"Invalid {name}={raw!r}, using default {default}")
        return default
    if value <= 0:
        logger.warning(f"Non-positive {name}={value}, using default {default}")
        return default
    return value


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

# precalculated_person_properties has the same merge-staleness problem, plus a second layer:
# each row is a verdict (matches true/false) evaluated against the person's properties at
# write time, and a merge changes the surviving person's property set — so re-attributing a
# row isn't enough, its verdict must be re-evaluated. The person-properties backfill can't
# repair these rows either: it stamps distinct_id = person UUID, so its rows never share a
# ReplacingMergeTree key with the realtime consumer's (team_id, condition, distinct_id) rows.
# Cohort membership here is queried by person_id (HogQLRealtimeCohortQuery), not distinct_id,
# so a stale row still tagged with the merged-away person keeps that person showing as a
# member. Since person_id isn't part of the sort key, re-emitting a row for the same
# (team_id, condition, distinct_id) with the surviving person_id overwrites it in place —
# including a matches=false verdict, which is what overwrites a stale matches=true row.

# Existing verdicts for a batch of overridden distinct_ids. Scoped to rows that already
# exist — a condition never evaluated for a distinct_id isn't "stale", it's the backfill's
# job to populate, not this reconciliation's.
EXISTING_PERSON_PROPERTIES_VERDICTS_QUERY = """
    SELECT
        distinct_id,
        condition,
        argMax(matches, (_timestamp, _offset)) AS matches,
        argMax(person_id, (_timestamp, _offset)) AS person_id
    FROM precalculated_person_properties
    WHERE team_id = %(team_id)s
      AND distinct_id IN %(distinct_ids)s
    GROUP BY distinct_id, condition
    FORMAT JSONEachRow
"""

# Current properties for a batch of surviving person_ids, deduped the same way the
# person_distinct_id_overrides queries above are (argMax by version, excluding deleted rows).
PERSON_PROPERTIES_QUERY = """
    SELECT
        id,
        argMax(properties, version) AS properties
    FROM person
    WHERE team_id = %(team_id)s
      AND id IN %(person_ids)s
    GROUP BY id
    HAVING argMax(is_deleted, version) = 0
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
    # Overrides lookback boundary shared by every team in a run; computed once by the
    # workflow so a team queued behind slow/retrying teams doesn't get a narrower window
    # than a team processed immediately (see reconcile_precalculated_events_activity).
    since: Optional[dt.datetime] = None

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


@dataclasses.dataclass
class ReconcilePersonPropertiesResult:
    """Result from reconciling one team's precalculated_person_properties."""

    overridden_distinct_ids: int
    verdicts_checked: int
    verdicts_corrected: int
    duration_seconds: float


@dataclasses.dataclass
class ReconciliationRunConfig:
    """Config computed once per workflow run and shared by every team.

    Reading env vars from workflow code would make replay non-deterministic if the value
    changed mid-run, so the workflow fetches both values through this one activity instead
    of reading them directly.
    """

    # Overrides lookback boundary; sharing one value means a team queued behind slow or
    # retrying teams gets the same window as a team processed immediately, instead of a
    # narrower one computed from a later wall-clock time.
    since: dt.datetime
    # Teams are reconciled with this much concurrency so one team's retries can't block
    # every other team in the run for hours.
    team_concurrency: int


@temporalio.activity.defn
async def get_reconciliation_run_config_activity() -> ReconciliationRunConfig:
    """Compute the run-wide lookback boundary and concurrency once, before any team runs."""
    logger = LOGGER.bind()
    overrides_lookback_hours = _positive_int_env("RECONCILE_EVENTS_OVERRIDES_LOOKBACK_HOURS", 48, logger)
    team_concurrency = _positive_int_env("RECONCILE_EVENTS_TEAM_CONCURRENCY", 5, logger)
    return ReconciliationRunConfig(
        since=dt.datetime.now(dt.UTC) - dt.timedelta(hours=overrides_lookback_hours),
        team_concurrency=team_concurrency,
    )


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


def _extract_person_property_filters(cohort: Cohort) -> list[PersonPropertyFilter]:
    """Extract person-property filters (conditionHash, bytecode, key) from a cohort's filter tree."""
    filters: list[PersonPropertyFilter] = []
    properties = (cohort.filters or {}).get("properties")
    if not properties:
        return filters

    def traverse(node: Any) -> None:
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        if node_type in ("AND", "OR"):
            for child in node.get("values", []):
                traverse(child)
            return
        if node_type != "person":
            return
        condition_hash = node.get("conditionHash")
        bytecode = node.get("bytecode")
        property_key = node.get("key")
        if not condition_hash or not bytecode or not property_key:
            return
        filters.append(
            PersonPropertyFilter(
                condition_hash=condition_hash, bytecode=bytecode, cohort_ids=[], property_key=property_key
            )
        )

    traverse(properties)
    return filters


@database_sync_to_async
def _get_realtime_person_property_filters(team_id: int) -> list[PersonPropertyFilter]:
    """Dedup person-property filters across a team's realtime cohorts, by condition_hash."""
    condition_map: dict[str, PersonPropertyFilter] = {}
    cohorts = Cohort.objects.filter(team_id=team_id, deleted=False, cohort_type=CohortType.REALTIME)
    for cohort in cohorts:
        for extracted in _extract_person_property_filters(cohort):
            existing = condition_map.get(extracted.condition_hash)
            if existing is None:
                extracted.cohort_ids = [cohort.id]
                condition_map[extracted.condition_hash] = extracted
            elif cohort.id not in existing.cohort_ids:
                existing.cohort_ids.append(cohort.id)

    return [condition_map[condition_hash] for condition_hash in sorted(condition_map)]


@temporalio.activity.defn
async def reconcile_team_precalculated_person_properties_activity(
    inputs: ReconcileTeamInputs,
) -> ReconcilePersonPropertiesResult:
    """Re-evaluate precalculated_person_properties verdicts for distinct_ids merged within the window.

    See the module-level comment above EXISTING_PERSON_PROPERTIES_VERDICTS_QUERY for why a
    verdict (not just an attribution) needs re-evaluating, and why matches=false must be
    written explicitly.
    """
    bind_contextvars()
    logger = LOGGER.bind(team_id=inputs.team_id)
    start_time = time.time()

    filters = await _get_realtime_person_property_filters(inputs.team_id)
    if not filters:
        return ReconcilePersonPropertiesResult(
            overridden_distinct_ids=0,
            verdicts_checked=0,
            verdicts_corrected=0,
            duration_seconds=time.time() - start_time,
        )
    combined_bytecode = combine_filter_bytecodes(filters)

    distinct_id_batch_size = _positive_int_env("RECONCILE_EVENTS_DISTINCT_ID_BATCH_SIZE", 1000, logger)
    kafka_flush_batch_size = _positive_int_env("RECONCILE_EVENTS_KAFKA_FLUSH_BATCH_SIZE", 1000, logger)
    overrides_lookback_hours = _positive_int_env("RECONCILE_EVENTS_OVERRIDES_LOOKBACK_HOURS", 48, logger)

    if inputs.full_scan:
        overrides_query = OVERRIDES_QUERY
        overrides_params: dict[str, Any] = {"team_id": inputs.team_id}
    else:
        since = inputs.since or (dt.datetime.now(dt.UTC) - dt.timedelta(hours=overrides_lookback_hours))
        overrides_query = RECENT_OVERRIDES_QUERY
        overrides_params = {"team_id": inputs.team_id, "since": since.strftime("%Y-%m-%d %H:%M:%S")}

    async with Heartbeater(details=(f"Loading person overrides for team {inputs.team_id}",)) as heartbeater:
        with tags_context(
            team_id=inputs.team_id,
            feature=Feature.BEHAVIORAL_COHORTS,
            product=Product.MESSAGING,
            query_type="precalculated_person_properties_reconciliation",
        ):
            async with get_client(team_id=inputs.team_id) as client:
                kafka_producer = get_producer(topic=KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES)
                kafka_results: list = []
                verdicts_checked = 0
                verdicts_corrected = 0
                overridden_distinct_ids = 0

                async def reconcile_batch(batch_overrides: dict[str, str]) -> None:
                    nonlocal verdicts_checked, verdicts_corrected

                    existing: dict[tuple[str, str], tuple[bool, str]] = {}
                    async for row in client.stream_query_as_jsonl(
                        EXISTING_PERSON_PROPERTIES_VERDICTS_QUERY,
                        query_parameters={
                            "team_id": inputs.team_id,
                            "distinct_ids": list(batch_overrides.keys()),
                        },
                    ):
                        existing[(str(row["distinct_id"]), str(row["condition"]))] = (
                            bool(row["matches"]),
                            str(row["person_id"]),
                        )

                    if not existing:
                        return

                    current_person_ids = sorted({batch_overrides[distinct_id] for distinct_id, _ in existing})
                    properties_by_person_id: dict[str, dict[str, Any]] = {}
                    async for row in client.stream_query_as_jsonl(
                        PERSON_PROPERTIES_QUERY,
                        query_parameters={"team_id": inputs.team_id, "person_ids": current_person_ids},
                    ):
                        person_id = str(row["id"])
                        properties_by_person_id[person_id] = parse_person_properties(row.get("properties"), person_id)

                    for (distinct_id, condition_hash), (stored_matches, stored_person_id) in existing.items():
                        verdicts_checked += 1
                        current_person_id = batch_overrides[distinct_id]
                        current_properties = properties_by_person_id.get(current_person_id, {})
                        hog_globals = {"person": {"properties": current_properties}}
                        filter_results = await asyncio.to_thread(
                            evaluate_combined_filters_with_fallback_sync,
                            combined_bytecode,
                            filters,
                            hog_globals,
                            current_person_id,
                        )
                        fresh_matches = bool(filter_results.get(condition_hash, False))

                        if fresh_matches == stored_matches and current_person_id == stored_person_id:
                            continue

                        produce_result = await asyncio.to_thread(
                            kafka_producer.produce,
                            topic=KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
                            data={
                                "team_id": inputs.team_id,
                                "distinct_id": distinct_id,
                                "person_id": current_person_id,
                                "condition": condition_hash,
                                "matches": fresh_matches,
                                "source": f"cohort_filter_{condition_hash}",
                            },
                        )
                        kafka_results.append(produce_result)
                        verdicts_corrected += 1

                        if len(kafka_results) >= kafka_flush_batch_size:
                            await flush_kafka_batch_async(kafka_results, kafka_producer, inputs.team_id, logger)
                            kafka_results.clear()

                batch_overrides: dict[str, str] = {}
                async for row in client.stream_query_as_jsonl(overrides_query, query_parameters=overrides_params):
                    batch_overrides[str(row["distinct_id"])] = str(row["person_id"])
                    overridden_distinct_ids += 1

                    if len(batch_overrides) >= distinct_id_batch_size:
                        await reconcile_batch(batch_overrides)
                        batch_overrides = {}
                        heartbeater.details = (
                            f"Checked {verdicts_checked} verdicts, corrected {verdicts_corrected} "
                            f"({overridden_distinct_ids} distinct_ids so far)",
                        )

                if batch_overrides:
                    await reconcile_batch(batch_overrides)

                if kafka_results:
                    await flush_kafka_batch_async(kafka_results, kafka_producer, inputs.team_id, logger)

    duration_seconds = time.time() - start_time
    logger.info(
        f"Reconciled precalculated_person_properties for team {inputs.team_id}: checked {verdicts_checked} "
        f"verdicts, corrected {verdicts_corrected} in {duration_seconds:.1f}s",
        overridden_distinct_ids=overridden_distinct_ids,
        verdicts_checked=verdicts_checked,
        verdicts_corrected=verdicts_corrected,
    )

    return ReconcilePersonPropertiesResult(
        overridden_distinct_ids=overridden_distinct_ids,
        verdicts_checked=verdicts_checked,
        verdicts_corrected=verdicts_corrected,
        duration_seconds=duration_seconds,
    )


@temporalio.activity.defn
async def reconcile_team_precalculated_events_activity(inputs: ReconcileTeamInputs) -> ReconcileTeamResult:
    """Re-emit precalculated_events rows whose person_id no longer matches the current mapping."""
    bind_contextvars()
    logger = LOGGER.bind(team_id=inputs.team_id)
    start_time = time.time()

    distinct_id_batch_size = _positive_int_env("RECONCILE_EVENTS_DISTINCT_ID_BATCH_SIZE", 1000, logger)
    kafka_flush_batch_size = _positive_int_env("RECONCILE_EVENTS_KAFKA_FLUSH_BATCH_SIZE", 1000, logger)
    overrides_lookback_hours = _positive_int_env("RECONCILE_EVENTS_OVERRIDES_LOOKBACK_HOURS", 48, logger)

    if inputs.full_scan:
        overrides_query = OVERRIDES_QUERY
        overrides_params: dict[str, Any] = {"team_id": inputs.team_id}
    else:
        # The workflow computes and shares one `since` boundary across every team in a run
        # (see ReconcilePrecalculatedEventsWorkflow.run); this per-activity fallback only
        # covers direct/manual activity invocations that skip the workflow.
        since = inputs.since or (dt.datetime.now(dt.UTC) - dt.timedelta(hours=overrides_lookback_hours))
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
                kafka_producer = get_producer(topic=KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS)
                kafka_results: list = []
                rows_checked = 0
                rows_corrected = 0
                overridden_distinct_ids = 0

                async def reconcile_batch(batch_overrides: dict[str, str]) -> None:
                    # Scan this team's precalculated_events for this batch of overridden
                    # distinct_ids and re-emit any row still carrying a superseded person_id.
                    nonlocal rows_checked, rows_corrected
                    async for row in client.stream_query_as_jsonl(
                        PRECALCULATED_EVENTS_BATCH_QUERY,
                        query_parameters={"team_id": inputs.team_id, "distinct_ids": list(batch_overrides.keys())},
                    ):
                        rows_checked += 1
                        distinct_id = str(row["distinct_id"])
                        current_person_id = batch_overrides[distinct_id]
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

                # Stream overrides in batches of distinct_id_batch_size and reconcile each
                # batch immediately, rather than materializing every overridden distinct_id
                # for the team before doing any reconciliation. Bounds per-activity memory
                # to O(batch size) regardless of how many distinct_ids a team merged within
                # the lookback window (or, on a full scan, ever).
                batch_overrides: dict[str, str] = {}
                async for row in client.stream_query_as_jsonl(overrides_query, query_parameters=overrides_params):
                    batch_overrides[str(row["distinct_id"])] = str(row["person_id"])
                    overridden_distinct_ids += 1

                    if len(batch_overrides) >= distinct_id_batch_size:
                        await reconcile_batch(batch_overrides)
                        batch_overrides = {}
                        heartbeater.details = (
                            f"Checked {rows_checked} rows, corrected {rows_corrected} "
                            f"({overridden_distinct_ids} distinct_ids so far)",
                        )

                if batch_overrides:
                    await reconcile_batch(batch_overrides)

                if not overridden_distinct_ids:
                    return ReconcileTeamResult(
                        overridden_distinct_ids=0,
                        rows_checked=0,
                        rows_corrected=0,
                        duration_seconds=time.time() - start_time,
                    )

                if kafka_results:
                    await flush_kafka_batch_async(kafka_results, kafka_producer, inputs.team_id, logger)

    duration_seconds = time.time() - start_time
    logger.info(
        f"Reconciled precalculated_events for team {inputs.team_id}: checked {rows_checked} rows, "
        f"corrected {rows_corrected} in {duration_seconds:.1f}s",
        overridden_distinct_ids=overridden_distinct_ids,
        rows_checked=rows_checked,
        rows_corrected=rows_corrected,
    )

    return ReconcileTeamResult(
        overridden_distinct_ids=overridden_distinct_ids,
        rows_checked=rows_checked,
        rows_corrected=rows_corrected,
        duration_seconds=duration_seconds,
    )


@temporalio.workflow.defn(name="reconcile-precalculated-events")
class ReconcilePrecalculatedEventsWorkflow(PostHogWorkflow):
    """Scheduled workflow that repairs precalculated_events and precalculated_person_properties
    rows made stale by person merges."""

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

        run_config = await temporalio.workflow.execute_activity(
            get_reconciliation_run_config_activity,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        workflow_logger.info(
            f"Reconciling precalculated_events for {len(team_ids)} teams (concurrency={run_config.team_concurrency})"
        )

        activity_retry_policy = temporalio.common.RetryPolicy(
            maximum_attempts=3,
            initial_interval=dt.timedelta(seconds=10),
            maximum_interval=dt.timedelta(minutes=1),
        )

        async def reconcile_team(team_id: int) -> tuple[ReconcileTeamResult, ReconcilePersonPropertiesResult]:
            team_inputs = ReconcileTeamInputs(team_id=team_id, full_scan=inputs.full_scan, since=run_config.since)
            # Sequential, not gathered: both activities touch the same team's ClickHouse data,
            # and keeping them in one place per team keeps a team's failure attributable to a
            # single activity instead of two racing against each other.
            events_result = await temporalio.workflow.execute_activity(
                reconcile_team_precalculated_events_activity,
                team_inputs,
                start_to_close_timeout=dt.timedelta(hours=2),
                heartbeat_timeout=dt.timedelta(minutes=5),
                retry_policy=activity_retry_policy,
            )
            properties_result = await temporalio.workflow.execute_activity(
                reconcile_team_precalculated_person_properties_activity,
                team_inputs,
                start_to_close_timeout=dt.timedelta(hours=2),
                heartbeat_timeout=dt.timedelta(minutes=5),
                retry_policy=activity_retry_policy,
            )
            return events_result, properties_result

        failed_teams: list[int] = []
        total_corrected = 0
        total_verdicts_corrected = 0
        for chunk_start in range(0, len(team_ids), run_config.team_concurrency):
            chunk = team_ids[chunk_start : chunk_start + run_config.team_concurrency]
            # return_exceptions=True: one team's failure shouldn't leave every other team
            # in (or after) its chunk stale.
            chunk_results = await asyncio.gather(
                *(reconcile_team(team_id) for team_id in chunk),
                return_exceptions=True,
            )
            for team_id, result in zip(chunk, chunk_results):
                if isinstance(result, BaseException):
                    failed_teams.append(team_id)
                    workflow_logger.exception(f"Reconciliation failed for team {team_id}: {result}")
                else:
                    events_result, properties_result = result
                    total_corrected += events_result.rows_corrected
                    total_verdicts_corrected += properties_result.verdicts_corrected

        workflow_logger.info(
            f"Reconciliation completed: corrected {total_corrected} event rows and "
            f"{total_verdicts_corrected} person-property verdicts across "
            f"{len(team_ids) - len(failed_teams)}/{len(team_ids)} teams"
            + (f", failed teams: {failed_teams}" if failed_teams else "")
        )
