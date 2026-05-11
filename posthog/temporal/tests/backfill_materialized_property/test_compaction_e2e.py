"""End-to-end test for ``CompactMaterializedColumnsWorkflow`` against real Postgres +
real ClickHouse with no activity stubs — the activity- and workflow-level tests mock
each other's seam, so neither catches mismatches between the planned SQL and what
ClickHouse actually executes.

The threshold gate is patched up so two seeded slots suffice to trigger compaction —
otherwise we'd need 91+ slots just to fool the check.
"""

import json
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import patch

import temporalio.worker
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.clickhouse.cluster import ClickhouseCluster, Query, get_cluster
from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.dmat_slot_assignments.sql import TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.temporal.backfill_materialized_property.activities import (
    activate_slots,
    assign_compaction_targets,
    assign_pending_columns,
    clear_compaction_targets,
    fail_slots,
    finalize_compaction,
    populate_slot_assignments,
    run_batched_mutation,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    CompactMaterializedColumnsInputs,
    CompactMaterializedColumnsWorkflow,
)

from products.event_definitions.backend.models.property_definition import PropertyType


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    yield get_cluster()


def _truncate_dmat_slot_assignments(cluster: ClickhouseCluster) -> None:
    """Ensure the dict-source table starts empty so this test's slots are the only rows
    pushed into the dictionary on every host."""
    cluster.map_all_hosts(Query(TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL())).result()


def _insert_test_events(cluster: ClickhouseCluster, team_id: int, count: int) -> list[tuple[str, str, str]]:
    """Insert `count` rows into sharded_events with `team_id` and known per-row property
    values in `dmat_string_50` (browser) and `dmat_string_60` (country). Returns the
    ground-truth tuples (uuid, browser_value, country_value) we'll later assert against.
    """
    rows: list[tuple[str, str, str]] = []
    for i in range(count):
        event_uuid = str(uuid.uuid4())
        browser = f"Browser-{i}"
        country = f"Country-{i}"
        rows.append((event_uuid, browser, country))

    table = EVENTS_DATA_TABLE()
    values_clauses: list[str] = []
    for event_uuid, browser, country in rows:
        properties = json.dumps({"browser": browser, "country": country}).replace("'", "''")
        values_clauses.append(
            f"('{event_uuid}', 'pageview', '{properties}', toDateTime('2026-01-01 00:00:00'), {team_id}, "
            f"'{browser}', '{country}')"
        )
    insert_sql = (
        f"INSERT INTO {table} (uuid, event, properties, timestamp, team_id, dmat_string_50, dmat_string_60) "
        f"VALUES {', '.join(values_clauses)}"
    )
    cluster.map_one_host_per_shard(Query(insert_sql)).result()
    return rows


def _fetch_dmat_columns_by_uuid(
    cluster: ClickhouseCluster, team_id: int, column_indexes: list[int]
) -> dict[str, dict[int, str | None]]:
    """Return `{row_uuid: {column_index: value}}` so old-vs-new column comparison can stay
    decoupled from the dynamic post-compaction indexes."""
    cols = ", ".join(f"dmat_string_{i}" for i in column_indexes)
    table = EVENTS_DATA_TABLE()
    rows = cluster.any_host(Query(f"SELECT uuid, {cols} FROM {table} WHERE team_id = {int(team_id)}")).result()
    by_uuid: dict[str, dict[int, str | None]] = {}
    for row in rows:
        row_uuid = str(row[0])
        by_uuid[row_uuid] = {idx: row[1 + n] for n, idx in enumerate(column_indexes)}
    return by_uuid


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestCompactionEndToEnd:
    @patch("posthog.temporal.backfill_materialized_property.activities.COMPACTION_FREE_COLUMN_THRESHOLD", 99)
    async def test_compaction_swaps_slot_indexes_and_preserves_column_data(self, team, cluster: ClickhouseCluster):
        """Compact two READY slots from sparse column indexes (50, 60) into the dense
        range (0, 1). After the workflow:

          * Both slots' `slot_index` is in the dense range.
          * Both slots' `compaction_target_slot_index` is None (cleared by finalize).
          * For every event row, the value the old column held is now also present
            in the new column. The old column is *not* cleared by this workflow
            (compaction is additive; freed columns are reusable next cycle).
        """
        _truncate_dmat_slot_assignments(cluster)

        prop_browser = await PropertyDefinition.objects.acreate(
            team=team,
            name="browser",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        prop_country = await PropertyDefinition.objects.acreate(
            team=team,
            name="country",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot_browser = await MaterializedColumnSlot.objects.acreate(
            team=team,
            property_definition=prop_browser,
            slot_index=50,
            state=MaterializedColumnSlotState.READY,
        )
        slot_country = await MaterializedColumnSlot.objects.acreate(
            team=team,
            property_definition=prop_country,
            slot_index=60,
            state=MaterializedColumnSlotState.READY,
        )

        event_count = 5
        ground_truth = _insert_test_events(cluster, team_id=team.id, count=event_count)

        workflow_id = str(uuid.uuid4())
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[CompactMaterializedColumnsWorkflow],
                # Real activities — no stubs. This is what makes the test end-to-end.
                activities=[
                    assign_compaction_targets,
                    assign_pending_columns,
                    populate_slot_assignments,
                    run_batched_mutation,
                    activate_slots,
                    finalize_compaction,
                    fail_slots,
                    clear_compaction_targets,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=8),
            ):
                await env.client.execute_workflow(
                    CompactMaterializedColumnsWorkflow.run,
                    CompactMaterializedColumnsInputs(cache_refresh_wait_seconds=0),
                    id=workflow_id,
                    task_queue=task_queue,
                )

        await slot_browser.arefresh_from_db()
        await slot_country.arefresh_from_db()

        # Both slots' indexes should now be in the dense range, distinct, and below the old indexes.
        assert slot_browser.slot_index is not None
        assert slot_country.slot_index is not None
        assert slot_browser.slot_index < 50, f"browser still on old column {slot_browser.slot_index}"
        assert slot_country.slot_index < 50, f"country still on old column {slot_country.slot_index}"
        assert slot_browser.slot_index != slot_country.slot_index
        assert slot_browser.compaction_target_slot_index is None
        assert slot_country.compaction_target_slot_index is None

        # Data correctness: for every row, the value that lived in dmat_string_50
        # should now also live in dmat_string_<browser_new_index>, and the same for
        # 60 → country_new_index.
        new_browser_idx = slot_browser.slot_index
        new_country_idx = slot_country.slot_index
        observed = _fetch_dmat_columns_by_uuid(
            cluster,
            team_id=team.id,
            column_indexes=[50, 60, new_browser_idx, new_country_idx],
        )
        assert len(observed) == event_count, "lost rows during compaction"
        for event_uuid, browser, country in ground_truth:
            row = observed[event_uuid]
            assert row[50] == browser, f"old browser column was overwritten for {event_uuid}"
            assert row[60] == country, f"old country column was overwritten for {event_uuid}"
            assert row[new_browser_idx] == browser, (
                f"compaction did not copy browser to dmat_string_{new_browser_idx} for {event_uuid}"
            )
            assert row[new_country_idx] == country, (
                f"compaction did not copy country to dmat_string_{new_country_idx} for {event_uuid}"
            )
