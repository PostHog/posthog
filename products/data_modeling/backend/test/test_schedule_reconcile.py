from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.test import SimpleTestCase

from temporalio.client import ScheduleAlreadyRunningError, ScheduleListActionStartWorkflow
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.freshness import UnsupportedFrequencyTargetError
from products.data_modeling.backend.logic.node_frequency import (
    get_declared_anchor,
    set_declared_anchor,
    set_declared_target,
)
from products.data_modeling.backend.logic.saved_query_dag_sync import promote_dag_view_nodes_to_matview
from products.data_modeling.backend.logic.schedule_reconcile import (
    DagScheduleTeardown,
    TeamScheduleTeardownError,
    apply_saved_query_frequency_anchor,
    convert_dag_to_tiers,
    delete_dag_schedules,
    delete_team_data_modeling_schedules,
    maybe_reconcile_dag,
    reconcile_dag_schedules,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.schedule import DATA_MODELING_EXECUTE_DAG_WORKFLOW
from products.data_modeling.backend.test.helpers import (
    no_existing_schedules,
    saved_query_node as _saved_query_node,
    table_node as _table_node,
    temporal_listing,
    warehouse_source_node as _warehouse_source_node,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"

M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)
H6 = timedelta(hours=6)


def _listing(schedule_id, workflow="data-modeling-execute-dag"):
    action = mock.Mock(spec=ScheduleListActionStartWorkflow, workflow=workflow)
    return mock.Mock(id=schedule_id, schedule=mock.Mock(action=action))


@pytest.mark.django_db
class TestReconcileDagSchedules(BaseTest):
    def test_creates_tier_scoped_schedule_and_deletes_stale_one(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)
        Edge.objects.create(team=self.team, dag=dag, source=matview, target=endpoint)
        set_declared_target(endpoint, M15)

        dag_id = str(dag.id)
        stale_id = tier_schedule_id(dag_id, H1)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(stale_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        # one 15min tier created, scoped to exactly the two schedulable nodes
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["id"], tier_schedule_id(dag_id, M15))
        created_inputs = create.call_args.kwargs["schedule"].action.args[0]
        self.assertEqual(sorted(created_inputs["node_ids"]), sorted([str(matview.id), str(endpoint.id)]))

        # tagged with the schedule type: get_v2_scheduled_dag_ids' unscoped sweep filters on it,
        # so an untagged tier schedule would make its DAG look un-migrated
        created_attrs = {pair.key.name: pair.value for pair in create.call_args.kwargs["search_attributes"]}
        self.assertEqual(created_attrs[POSTHOG_SCHEDULE_TYPE_KEY.name], DATA_MODELING_EXECUTE_DAG_WORKFLOW)

        # the stale H1 schedule is removed; nothing to update
        update.assert_not_called()
        delete.assert_called_once_with(temporal, schedule_id=stale_id)

    def test_rewrites_persisting_tier_without_create_or_delete(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)
        Edge.objects.create(team=self.team, dag=dag, source=matview, target=endpoint)
        set_declared_target(endpoint, M15)

        dag_id = str(dag.id)
        existing_id = tier_schedule_id(dag_id, M15)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(existing_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        # the 15min tier already exists, so it is rewritten in place — no create, no delete
        update.assert_called_once()
        self.assertEqual(update.call_args.kwargs["id"], existing_id)
        create.assert_not_called()
        delete.assert_not_called()

    def test_anchored_node_gets_its_own_pinned_schedule(self):
        # an anchor that never reaches Temporal is a silent fleet-wide no-op: the node keeps
        # firing on its hash slot while the operator believes it is pinned
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        spread = _saved_query_node(self.team, dag, "spread", NodeType.MAT_VIEW)
        pinned = _saved_query_node(self.team, dag, "pinned", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=spread)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=pinned)
        set_declared_target(spread, M15)
        set_declared_target(pinned, M15)
        set_declared_anchor(pinned, 120)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                return
                yield

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()),
        ):
            reconcile_dag_schedules(dag)

        dag_id = str(dag.id)
        created = {call.kwargs["id"]: call.kwargs["schedule"] for call in create.call_args_list}
        # the raw anchor (02:00) reduces to phase 0 within a 15min cadence, and the schedule id
        # carries the canonical phase so equivalent anchors share one schedule
        self.assertEqual(set(created), {tier_schedule_id(dag_id, M15), tier_schedule_id(dag_id, M15, 0)})

        anchored = created[tier_schedule_id(dag_id, M15, 0)]
        self.assertEqual(anchored.action.args[0]["node_ids"], [str(pinned.id)])
        self.assertEqual(anchored.spec.time_zone_name, "UTC")
        self.assertEqual(anchored.spec.jitter, timedelta(minutes=1))
        minutes = {r.start for r in anchored.spec.calendars[0].minute}
        self.assertEqual(minutes, {0, 15, 30, 45})

    def test_apply_saved_query_frequency_anchor_writes_nodes_and_queues_reconcile(self):
        dag = DAG.get_or_create_default(self.team)
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        assert matview.saved_query is not None
        with mock.patch(f"{RECONCILE}.maybe_reconcile_dag") as reconcile:
            written = apply_saved_query_frequency_anchor(matview.saved_query, 120)
        self.assertEqual(written, 1)
        matview.refresh_from_db()
        self.assertEqual(get_declared_anchor(matview), 120)
        reconcile.assert_called_once()

        with mock.patch(f"{RECONCILE}.maybe_reconcile_dag"):
            apply_saved_query_frequency_anchor(matview.saved_query, None)
        matview.refresh_from_db()
        self.assertIsNone(get_declared_anchor(matview))

    def test_rolls_back_created_tiers_and_keeps_legacy_schedule_on_failure(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        ep_fast = _saved_query_node(self.team, dag, "fast", NodeType.ENDPOINT)
        ep_slow = _saved_query_node(self.team, dag, "slow", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=ep_fast)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=ep_slow)
        set_declared_target(ep_fast, M15)
        set_declared_target(ep_slow, H6)

        legacy_id = str(dag.id)  # migration-era single schedule, slated for deletion once tiers exist

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(legacy_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        created_ids: list[str] = []

        async def failing_create(*_args, **kwargs):
            created_ids.append(kwargs["id"])
            if len(created_ids) >= 2:  # second tier creation fails partway through the migration
                raise RuntimeError("temporal unavailable")

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock(side_effect=failing_create)),
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            with self.assertRaises(RuntimeError):
                reconcile_dag_schedules(dag)

        # the one successfully-created tier is rolled back; the legacy schedule is never deleted,
        # so the DAG stays fully covered at its current cadence rather than opening a gap
        delete.assert_called_once_with(temporal, schedule_id=created_ids[0])
        self.assertNotEqual(created_ids[0], legacy_id)

    def test_refuses_to_unschedule_covered_dag_without_targets(self):
        # a covered DAG with no targets means unseeded conversion, not a wind-down —
        # converging to zero schedules would silently stop all materialization
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)

        legacy_id = str(dag.id)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(legacy_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        create.assert_not_called()
        delete.assert_not_called()

    def test_sweeps_legacy_schedule_when_dag_has_no_schedulable_nodes(self):
        # a DAG holding only source tables has nothing to seed, so the unseeded-conversion
        # guard must not apply: its legacy schedule just fires no-op execute-dag runs forever
        dag = DAG.get_or_create_default(self.team)
        _table_node(self.team, dag, "events", {"origin": "posthog"})

        legacy_id = str(dag.id)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(legacy_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        create.assert_not_called()
        delete.assert_called_once_with(temporal, schedule_id=legacy_id)

    def test_winds_down_tier_schedules_when_all_targets_cleared(self):
        # reverting/clearing the last target leaves empty desired tiers; once tier schedules exist
        # that is a deliberate wind-down, so the stale tier must be torn down rather than left
        # firing execute-dag on node_ids that no longer materialize
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        # no target on any node -> desired tiers empty, but a tier schedule is still live

        stale_tier = tier_schedule_id(str(dag.id), M15)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(stale_tier)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        create.assert_not_called()
        delete.assert_called_once_with(temporal, schedule_id=stale_tier)

    def test_concurrent_create_converges_to_update_without_rollback(self):
        # a concurrent reconcile already created the tier; the loser must converge onto it,
        # not roll it back — rolling back would delete the winner's live schedule
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        set_declared_target(endpoint, M15)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                return
                yield  # pragma: no cover — empty async generator

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(
                f"{RECONCILE}.a_create_schedule",
                new=mock.AsyncMock(side_effect=ScheduleAlreadyRunningError()),
            ),
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        update.assert_called_once()
        self.assertEqual(update.call_args.kwargs["id"], tier_schedule_id(str(dag.id), M15))
        delete.assert_not_called()

    def test_refuses_non_bucket_tier_before_touching_temporal(self):
        # the guard must fire before any Temporal call — a non-bucket tier would crash
        # build_schedule_spec mid-apply and leave the DAG partially reconciled
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        set_declared_target(endpoint, timedelta(minutes=45))

        with mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock()) as connect:
            with self.assertRaises(UnsupportedFrequencyTargetError):
                reconcile_dag_schedules(dag)
        connect.assert_not_called()

    def test_clamps_a_target_finer_than_its_source_can_deliver(self):
        # a matview target drifted below its source floor (e.g. the import later slowed to 6h):
        # reconcile must schedule it at the source floor, not the wasteful finer cadence
        dag = DAG.get_or_create_default(self.team)
        source = _warehouse_source_node(self.team, dag, sync_frequency_interval=H6)
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)
        set_declared_target(matview, M15)

        dag_id = str(dag.id)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                return
                yield  # pragma: no cover — empty async generator

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
        ):
            reconcile_dag_schedules(dag)

        # clamped to the 6h source floor, not the declared 15min
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["id"], tier_schedule_id(dag_id, H6))


@pytest.mark.django_db
class TestMaybeReconcileDag(BaseTest):
    def _dag_with_target(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        set_declared_target(endpoint, M15)
        return dag

    def _temporal_listing(self, schedule_ids):
        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                for schedule_id in schedule_ids:
                    yield _listing(schedule_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules
        return temporal

    def test_flag_off_never_touches_temporal(self):
        dag = self._dag_with_target()
        with (
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=False),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock()) as connect,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        connect.assert_not_called()

    def test_untiered_dag_is_left_alone(self):
        # a legacy single-schedule DAG converts only via the conversion command; a mutation
        # trigger must neither unschedule it nor create tiers next to live v1 schedules
        dag = self._dag_with_target()
        with (
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            mock.patch(
                f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=self._temporal_listing([str(dag.id)]))
            ),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        create.assert_not_called()
        update.assert_not_called()
        delete.assert_not_called()

    def test_tiered_dag_reconciles_after_commit(self):
        dag = self._dag_with_target()
        tier_id = tier_schedule_id(str(dag.id), M15)
        with (
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            mock.patch(
                f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=self._temporal_listing([tier_id]))
            ),
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        update.assert_called_once()
        self.assertEqual(update.call_args.kwargs["id"], tier_id)

    def test_reconcile_failure_never_raises_past_commit(self):
        dag = self._dag_with_target()
        with (
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(side_effect=RuntimeError("temporal down"))),
            mock.patch(f"{RECONCILE}.capture_exception") as capture,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        capture.assert_called_once()


@pytest.mark.django_db
class TestPromoteDagViewNodesToMatview(BaseTest):
    def _backed(self, dag, name, node_type):
        node = _saved_query_node(self.team, dag, name, node_type)
        saved_query = node.saved_query
        assert saved_query is not None
        saved_query.table = DataWarehouseTable.objects.create(team=self.team, name=f"{name}_tbl", format="Delta")
        saved_query.save()
        return node

    def test_retypes_only_table_backed_view_nodes(self):
        dag = DAG.get_or_create_default(self.team)
        stranded = self._backed(dag, "stranded", NodeType.VIEW)
        endpoint = self._backed(dag, "endpoint_backed", NodeType.ENDPOINT)
        ephemeral = _saved_query_node(self.team, dag, "ephemeral", NodeType.VIEW)

        assert promote_dag_view_nodes_to_matview(dag) == 1

        for node in (stranded, endpoint, ephemeral):
            node.refresh_from_db()
        assert stranded.type == NodeType.MAT_VIEW
        # A view with no backing table is a real ephemeral view; retyping it would schedule
        # materializations for something that has nothing to materialize.
        assert ephemeral.type == NodeType.VIEW
        assert endpoint.type == NodeType.ENDPOINT

    def test_conversion_to_tiers_repairs_stranded_nodes(self):
        # The v1 sweep that follows conversion is what makes a view-typed node go dark, so the
        # repair has to happen as part of converting, not on some later pass.
        dag = DAG.get_or_create_default(self.team)
        stranded = self._backed(dag, "stranded", NodeType.VIEW)
        set_declared_target(stranded, M15)

        with (
            mock.patch(f"{RECONCILE}.sync_connect", return_value=no_existing_schedules()),
            mock.patch(f"{RECONCILE}.async_connect", return_value=no_existing_schedules()),
            mock.patch(f"{RECONCILE}.a_create_schedule"),
        ):
            convert_dag_to_tiers(dag)

        stranded.refresh_from_db()
        assert stranded.type == NodeType.MAT_VIEW


class TestDeleteDagSchedules(SimpleTestCase):
    def _run(self, schedule_ids, *, delete=None):
        temporal = temporal_listing(schedule_ids)
        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=delete or mock.AsyncMock()) as deleter,
        ):
            return delete_dag_schedules("dag-1"), deleter

    def test_deletes_every_listed_schedule_whatever_its_id_scheme(self):
        # the listing is authoritative, so a tier, a bare legacy id and an off-scheme id all go
        teardown, deleter = self._run(["dag-1:3600", "dag-1", "dag-1-legacy"])

        assert teardown.ok
        assert teardown.deleted == ("dag-1", "dag-1-legacy", "dag-1:3600")
        assert deleter.await_count == 3

    def test_already_deleted_schedule_is_not_a_failure(self):
        delete = mock.AsyncMock(side_effect=RPCError("gone", RPCStatusCode.NOT_FOUND, b""))
        teardown, _ = self._run(["dag-1:3600"], delete=delete)

        assert teardown.ok
        assert teardown.deleted == ()

    def test_listing_failure_reports_not_ok_and_deletes_nothing(self):
        # the caller keys "may I drop the DAG row?" off ok: the listing is the only way back to
        # these schedules once the row is gone
        temporal = mock.Mock()
        temporal.list_schedules = mock.AsyncMock(side_effect=RuntimeError("temporal down"))
        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as deleter,
        ):
            teardown = delete_dag_schedules("dag-1")

        assert not teardown.ok
        assert teardown.deleted == ()
        deleter.assert_not_awaited()

    def test_one_failed_delete_reports_not_ok_but_still_deletes_the_others(self):
        def _fail_the_tier(_temporal, schedule_id):
            if schedule_id == "dag-1:3600":
                raise RPCError("boom", RPCStatusCode.INTERNAL, b"")

        delete = mock.AsyncMock(side_effect=_fail_the_tier)
        teardown, deleter = self._run(["dag-1:3600", "dag-1:86400"], delete=delete)

        assert not teardown.ok
        assert teardown.deleted == ("dag-1:86400",)
        assert deleter.await_count == 2


class TestDeleteTeamDataModelingSchedules(BaseTest):
    def test_sweeps_both_halves_for_a_team_converted_to_dag_schedules(self):
        # Conversion nulls sync_frequency_interval, so no field can decide which half to sweep.
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="converted_query",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            sync_frequency_interval=None,
        )
        dag = DAG.objects.create(team=self.team, name="Default")

        with (
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.delete_schedule") as delete_query,
            mock.patch(
                f"{RECONCILE}.delete_dag_schedules",
                return_value=DagScheduleTeardown(ok=True, deleted=(str(dag.id),)),
            ) as delete_dag,
        ):
            delete_team_data_modeling_schedules(self.team.id)

        delete_query.assert_called_once_with(mock.ANY, schedule_id=str(saved_query.id))
        delete_dag.assert_called_once_with(str(dag.id))

    def test_raises_when_a_dag_teardown_fails_so_the_activity_retries(self):
        DAG.objects.create(team=self.team, name="Default")

        with mock.patch(
            f"{RECONCILE}.delete_dag_schedules",
            return_value=DagScheduleTeardown(ok=False, deleted=()),
        ):
            with pytest.raises(TeamScheduleTeardownError):
                delete_team_data_modeling_schedules(self.team.id)
