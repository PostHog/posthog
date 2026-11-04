from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics.types import FeatureFlagResult
from temporalio.client import ScheduleActionStartWorkflow, ScheduleAlreadyRunningError, ScheduleListActionStartWorkflow
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.freshness import UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError
from products.data_modeling.backend.logic.node_frequency import (
    get_declared_anchor,
    get_declared_pin,
    get_declared_target,
    set_declared_anchor,
    set_declared_pin,
    set_declared_target,
)
from products.data_modeling.backend.logic.refresh_floor import REFRESH_FLOOR_FLAG, read_organization_plan_refresh_floor
from products.data_modeling.backend.logic.saved_query_dag_sync import promote_dag_view_nodes_to_matview
from products.data_modeling.backend.logic.schedule_reconcile import (
    DagScheduleTeardown,
    OrganizationReconcileError,
    PlanFloorUnavailableError,
    TeamScheduleTeardownError,
    apply_saved_query_frequency_anchor,
    apply_saved_query_frequency_target,
    bootstrap_dag_to_tiers,
    convert_dag_to_tiers,
    delete_dag_schedules,
    delete_team_data_modeling_schedules,
    maybe_reconcile_dag,
    reconcile_dag_schedules,
    reconcile_organization_dags,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.schedule import DATA_MODELING_EXECUTE_DAG_WORKFLOW, build_schedule_spec
from products.data_modeling.backend.test.helpers import (
    no_existing_schedules,
    saved_query_node as _saved_query_node,
    table_node as _table_node,
    temporal_listing,
    warehouse_source_node as _warehouse_source_node,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"
REFRESH_FLOOR = "products.data_modeling.backend.logic.refresh_floor"
FLAG_RESULT = f"{REFRESH_FLOOR}.posthoganalytics.get_feature_flag_result"

M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)
H6 = timedelta(hours=6)
DAY = timedelta(days=1)


def _free_plan_floor(payload):
    def evaluate(key, distinct_id, *, person_properties=None, **_kwargs):
        enabled = (person_properties or {}).get("organization_plan") == "free"
        return FeatureFlagResult(key=key, enabled=enabled, variant=None, payload=payload, reason=None)

    return evaluate


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

    def test_sweeps_legacy_schedule_when_dag_has_no_schedulable_nodes(self):
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

    def test_listed_tier_that_is_already_gone_is_recreated_and_stays_materialized(self):
        # the listing reads Temporal's eventually consistent visibility store, so it can name a
        # tier that is already deleted; a failed bootstrap would mark the query not materialized
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        set_declared_target(endpoint, M15)
        saved_query = endpoint.saved_query
        assert saved_query is not None
        saved_query.is_materialized = True
        saved_query.save(update_fields=["is_materialized"])

        tier_id = tier_schedule_id(str(dag.id), M15)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(tier_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(
                f"{RECONCILE}.a_update_schedule",
                new=mock.AsyncMock(side_effect=RPCError("schedule not found", RPCStatusCode.NOT_FOUND, b"")),
            ),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
            self.captureOnCommitCallbacks(execute=True),
        ):
            bootstrap_dag_to_tiers(dag, requested_by=saved_query)

        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["id"], tier_id)
        delete.assert_not_called()
        saved_query.refresh_from_db()
        self.assertTrue(saved_query.is_materialized)

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

    def _temporal_with_tier(self, *schedule_ids_and_node_ids):
        tiers = dict(zip(schedule_ids_and_node_ids[::2], schedule_ids_and_node_ids[1::2]))
        temporal = self._temporal_listing(list(tiers))

        def handle_for(schedule_id):
            action = mock.Mock(spec=ScheduleActionStartWorkflow, args=[{"node_ids": tiers[schedule_id]}])
            description = mock.Mock(schedule=mock.Mock(action=action))
            return mock.Mock(describe=mock.AsyncMock(return_value=description))

        temporal.get_schedule_handle = handle_for
        return temporal

    def test_dag_with_no_schedule_regains_a_tier(self):
        dag = self._dag_with_target()
        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=self._temporal_listing([]))),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["id"], tier_schedule_id(str(dag.id), M15))
        delete.assert_not_called()

    def test_tiered_dag_reconciles_after_commit(self):
        dag = self._dag_with_target()
        tier_id = tier_schedule_id(str(dag.id), M15)
        with (
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

    @parameterized.expand(
        [
            ("unpinned_runs_at_the_consumer_cadence", False, True, {H6: ["upstream", "consumer"]}),
            ("pinned_keeps_its_own_cadence", True, True, {DAY: ["upstream"], H6: ["consumer"]}),
            ("pinned_holds_back_a_consumer_with_no_fresher_parent", True, False, {DAY: ["upstream", "consumer"]}),
        ]
    )
    def test_upstream_slower_than_its_consumer_keeps_its_setting(
        self, _name, pinned, consumer_reads_source, expected_tiers
    ):
        dag = DAG.get_or_create_default(self.team)
        source = _warehouse_source_node(self.team, dag, sync_frequency_interval=H1)
        upstream = _saved_query_node(self.team, dag, "org_universe", NodeType.MAT_VIEW)
        consumer = _saved_query_node(self.team, dag, "maps", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=upstream)
        Edge.objects.create(team=self.team, dag=dag, source=upstream, target=consumer)
        if consumer_reads_source:
            Edge.objects.create(team=self.team, dag=dag, source=source, target=consumer)
        set_declared_target(upstream, DAY)
        set_declared_target(consumer, H6)
        if pinned:
            set_declared_pin(upstream, True)

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=self._temporal_listing([]))),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)

        ids = {"upstream": str(upstream.id), "consumer": str(consumer.id)}
        created = {
            call.kwargs["id"]: sorted(call.kwargs["schedule"].action.args[0]["node_ids"])
            for call in create.call_args_list
        }
        self.assertEqual(
            created,
            {
                tier_schedule_id(str(dag.id), cadence): sorted(ids[name] for name in names)
                for cadence, names in expected_tiers.items()
            },
        )
        upstream.refresh_from_db()
        self.assertEqual(get_declared_target(upstream), DAY)

    @parameterized.expand(
        [
            (
                "free_plan_runs_at_the_floor",
                False,
                _free_plan_floor({"min_interval": "6hour", "clamp_existing": True}),
                H6,
            ),
            (
                "paid_plan_is_not_floored",
                True,
                _free_plan_floor({"min_interval": "6hour", "clamp_existing": True}),
                M15,
            ),
            (
                "daily_floor_uses_the_sync_frequency_name",
                False,
                _free_plan_floor({"min_interval": "24hour", "clamp_existing": True}),
                DAY,
            ),
            (
                "existing_cadence_kept_until_clamp_existing",
                False,
                _free_plan_floor({"min_interval": "6hour", "clamp_existing": False}),
                M15,
            ),
        ]
    )
    def test_plan_floor_coarsens_the_schedule_and_keeps_the_saved_cadence(
        self, _name, has_active_subscription, flag, expected_tier
    ):
        self.organization.has_active_subscription = has_active_subscription
        self.organization.save(update_fields=["has_active_subscription"])
        dag = self._dag_with_target()

        with (
            mock.patch(FLAG_RESULT, side_effect=flag),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=self._temporal_listing([]))),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)

        self.assertEqual(
            [call.kwargs["id"] for call in create.call_args_list], [tier_schedule_id(str(dag.id), expected_tier)]
        )
        endpoint = Node.objects.get(dag=dag, type=NodeType.ENDPOINT)
        self.assertEqual(get_declared_target(endpoint), M15)

    @parameterized.expand(
        [
            ("flag_raises", mock.Mock(side_effect=RuntimeError("flags down"))),
            ("bad_payload", _free_plan_floor({"min_interval": "soon"})),
        ]
    )
    def test_unreadable_plan_floor_leaves_existing_schedules_alone(self, _name, flag):
        self.organization.has_active_subscription = False
        self.organization.save(update_fields=["has_active_subscription"])
        dag = self._dag_with_target()
        endpoint = Node.objects.get(dag=dag, type=NodeType.ENDPOINT)
        temporal = self._temporal_with_tier(tier_schedule_id(str(dag.id), H6), [str(endpoint.id)])

        with (
            mock.patch(FLAG_RESULT, side_effect=flag),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
            mock.patch(f"{RECONCILE}.capture_exception") as capture,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)

        create.assert_not_called()
        update.assert_not_called()
        delete.assert_not_called()
        capture.assert_called_once()

    def test_organization_reconcile_only_touches_dags_entirely_on_tier_schedules(self):
        tiered = self._dag_with_target()
        schedules = {str(tiered.id): {tier_schedule_id(str(tiered.id), H6)}}
        for name, schedule_ids in (
            ("never scheduled", set()),
            ("legacy", {"{id}"}),
            ("migrating", {"{id}", "{id}:21600"}),
        ):
            dag = DAG.objects.create(team=self.team, name=name)
            schedules[str(dag.id)] = {schedule_id.format(id=dag.id) for schedule_id in schedule_ids}

        with (
            mock.patch(f"{RECONCILE}.list_existing_schedule_ids", side_effect=schedules.__getitem__),
            mock.patch(f"{RECONCILE}.reconcile_dag_schedules", return_value=[]) as reconcile,
        ):
            reconcile_organization_dags(str(self.organization.id))

        self.assertEqual([call.args[0] for call in reconcile.call_args_list], [tiered])

    def test_organization_reconcile_tries_every_dag_then_raises_so_the_task_retries(self):
        first = self._dag_with_target()
        second = DAG.objects.create(team=self.team, name="second")

        with (
            mock.patch(f"{RECONCILE}.list_existing_schedule_ids", side_effect=lambda dag_id: {f"{dag_id}:21600"}),
            mock.patch(f"{RECONCILE}.reconcile_dag_schedules", side_effect=RuntimeError("temporal down")) as reconcile,
            self.assertRaises(OrganizationReconcileError),
        ):
            reconcile_organization_dags(str(self.organization.id))

        self.assertCountEqual([call.args[0] for call in reconcile.call_args_list], [first, second])

    def test_organization_reconcile_raises_when_a_stale_schedule_cannot_be_deleted(self):
        dag = self._dag_with_target()
        stale_id = tier_schedule_id(str(dag.id), H1)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(stale_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.list_existing_schedule_ids", return_value={stale_id}),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock(side_effect=RuntimeError("temporal down"))),
            self.assertRaises(OrganizationReconcileError),
        ):
            reconcile_organization_dags(str(self.organization.id))

        create.assert_called_once()

    def test_unreadable_plan_floor_leaves_a_legacy_whole_dag_schedule_running(self):
        dag = DAG.objects.create(team=self.team, name="legacy")
        temporal = self._temporal_with_tier(str(dag.id), None)

        with (
            mock.patch(FLAG_RESULT, side_effect=RuntimeError("flags down")),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
            self.assertRaises(PlanFloorUnavailableError),
        ):
            reconcile_dag_schedules(dag)

        delete.assert_not_called()
        update.assert_not_called()

    def test_unreadable_plan_floor_still_takes_a_cleared_node_off_its_schedule(self):
        dag = self._dag_with_target()
        endpoint = Node.objects.get(dag=dag, type=NodeType.ENDPOINT)
        cleared = _saved_query_node(self.team, dag, "cleared", NodeType.MAT_VIEW)
        kept_tier = tier_schedule_id(str(dag.id), H6, 30)
        emptied_tier = tier_schedule_id(str(dag.id), DAY)
        temporal = self._temporal_with_tier(
            kept_tier, [str(endpoint.id), str(cleared.id)], emptied_tier, [str(cleared.id)]
        )

        with (
            mock.patch(FLAG_RESULT, side_effect=RuntimeError("flags down")),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
            self.assertRaises(PlanFloorUnavailableError),
        ):
            reconcile_dag_schedules(dag)

        create.assert_not_called()
        delete.assert_awaited_once_with(temporal, schedule_id=emptied_tier)
        update.assert_awaited_once()
        self.assertEqual(update.call_args.kwargs["id"], kept_tier)
        schedule = update.call_args.kwargs["schedule"]
        self.assertEqual(schedule.action.args[0]["node_ids"], [str(endpoint.id)])
        self.assertEqual(
            schedule.spec,
            build_schedule_spec(entity_id=dag.id, interval=H6, team_timezone=self.team.timezone, anchor_minutes=30),
        )

    @parameterized.expand(
        [
            ("self_hosted_never_loads_definitions", False, False, None, True),
            ("cloud_with_the_sdk_disabled", True, True, None, True),
            ("cloud_with_definitions_that_failed_to_load", True, False, None, False),
            ("cloud_with_empty_definitions", True, False, [], False),
            ("cloud_after_the_flag_was_deleted", True, False, [{"key": "other-flag"}], True),
            ("cloud_with_a_flag_it_could_not_evaluate", True, False, [{"key": REFRESH_FLOOR_FLAG}], True),
        ]
    )
    def test_no_flag_result_only_refuses_when_definitions_failed_to_load(
        self, _name, cloud, disabled, definitions, evaluated
    ):
        with (
            mock.patch(FLAG_RESULT, return_value=None),
            mock.patch(f"{REFRESH_FLOOR}.run_mode", return_value=mock.Mock(is_deployed_cloud=cloud)),
            mock.patch(f"{REFRESH_FLOOR}.posthoganalytics.disabled", disabled),
            mock.patch(f"{REFRESH_FLOOR}.posthoganalytics.feature_flag_definitions", return_value=definitions),
        ):
            reading = read_organization_plan_refresh_floor(self.organization)

        self.assertIsNone(reading.floor)
        self.assertEqual(reading.evaluated, evaluated)

    @parameterized.expand(
        [
            ("first_cadence_is_refused", None, H6, False),
            ("speed_up_is_refused", DAY, H6, False),
            ("slowing_down_is_allowed", H6, DAY, True),
            ("re_saving_is_allowed", H6, H6, True),
        ]
    )
    def test_unreadable_plan_floor_only_refuses_a_speed_up(self, _name, stored, target, allowed):
        node = _saved_query_node(self.team, DAG.get_or_create_default(self.team), "mv", NodeType.MAT_VIEW)
        if stored is not None:
            set_declared_target(node, stored)
        assert node.saved_query is not None

        with (
            mock.patch(FLAG_RESULT, side_effect=RuntimeError("flags down")),
            mock.patch(f"{RECONCILE}.maybe_reconcile_dag"),
        ):
            if allowed:
                apply_saved_query_frequency_target(node.saved_query, target)
            else:
                with self.assertRaisesMessage(UnsatisfiableFrequencyError, "Couldn't check your plan"):
                    apply_saved_query_frequency_target(node.saved_query, target)

        node.refresh_from_db()
        self.assertEqual(get_declared_target(node), target if allowed else stored)

    def test_unreadable_plan_floor_refuses_a_bootstrap_before_seeding_targets(self):
        node = _saved_query_node(self.team, DAG.get_or_create_default(self.team), "mv", NodeType.MAT_VIEW)
        assert node.saved_query is not None
        node.saved_query.sync_frequency_interval = M15
        node.saved_query.save(update_fields=["sync_frequency_interval"])

        with (
            mock.patch(FLAG_RESULT, side_effect=RuntimeError("flags down")),
            self.assertRaises(PlanFloorUnavailableError),
        ):
            bootstrap_dag_to_tiers(node.dag)

        node.refresh_from_db()
        self.assertIsNone(get_declared_target(node))

    def test_a_pin_is_refused_when_a_consumer_saved_a_finer_cadence_than_the_enforced_plan_floor(self):
        self.organization.has_active_subscription = False
        self.organization.save(update_fields=["has_active_subscription"])
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        view = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        consumer = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=view)
        Edge.objects.create(team=self.team, dag=dag, source=view, target=consumer)
        set_declared_target(view, M15)
        set_declared_pin(view, True)
        set_declared_target(consumer, M15)
        assert view.saved_query is not None

        with (
            mock.patch(FLAG_RESULT, side_effect=_free_plan_floor({"min_interval": "6hour", "clamp_existing": True})),
            mock.patch(f"{RECONCILE}.maybe_reconcile_dag"),
            self.assertRaisesMessage(UnsatisfiableFrequencyError, "Can't pin this view"),
        ):
            apply_saved_query_frequency_target(view.saved_query, H6)

        view.refresh_from_db()
        self.assertEqual(get_declared_target(view), M15)

    def test_a_reader_of_a_managed_view_slowed_by_the_plan_floor_can_resave_its_cadence(self):
        self.organization.has_active_subscription = False
        self.organization.save(update_fields=["has_active_subscription"])
        dag = DAG.get_or_create_default(self.team)
        viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        )
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        managed_view = _saved_query_node(self.team, dag, "managed_view", NodeType.MAT_VIEW)
        assert managed_view.saved_query is not None
        managed_view.saved_query.managed_viewset = viewset
        managed_view.saved_query.save(update_fields=["managed_viewset"])
        set_declared_target(managed_view, M15)
        reader = _saved_query_node(self.team, dag, "reader", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=managed_view)
        Edge.objects.create(team=self.team, dag=dag, source=managed_view, target=reader)
        set_declared_target(reader, M15)
        assert reader.saved_query is not None

        with (
            mock.patch(FLAG_RESULT, side_effect=_free_plan_floor({"min_interval": "6hour", "clamp_existing": True})),
            mock.patch(f"{RECONCILE}.maybe_reconcile_dag"),
        ):
            apply_saved_query_frequency_target(reader.saved_query, M15)

        reader.refresh_from_db()
        self.assertEqual(get_declared_target(reader), M15)

    def test_saving_a_cadence_finer_than_the_plan_floor_is_refused(self):
        self.organization.has_active_subscription = False
        self.organization.save(update_fields=["has_active_subscription"])
        node = _saved_query_node(self.team, DAG.get_or_create_default(self.team), "mv", NodeType.MAT_VIEW)
        set_declared_target(node, DAY)
        assert node.saved_query is not None

        with (
            mock.patch(FLAG_RESULT, side_effect=_free_plan_floor({"min_interval": "6hour"})),
            mock.patch(f"{RECONCILE}.maybe_reconcile_dag"),
            self.assertRaisesMessage(UnsatisfiableFrequencyError, "on your plan"),
        ):
            apply_saved_query_frequency_target(node.saved_query, M15)

        node.refresh_from_db()
        self.assertEqual(get_declared_target(node), DAY)

    def test_resaving_a_cadence_saved_before_the_plan_floor_is_accepted(self):
        self.organization.has_active_subscription = False
        self.organization.save(update_fields=["has_active_subscription"])
        node = _saved_query_node(self.team, DAG.get_or_create_default(self.team), "mv", NodeType.MAT_VIEW)
        set_declared_target(node, M15)
        assert node.saved_query is not None

        with (
            mock.patch(FLAG_RESULT, side_effect=_free_plan_floor({"min_interval": "6hour"})),
            mock.patch(f"{RECONCILE}.maybe_reconcile_dag"),
        ):
            apply_saved_query_frequency_target(node.saved_query, M15)

        node.refresh_from_db()
        self.assertEqual(get_declared_target(node), M15)

    def test_a_pin_on_its_own_keeps_the_stored_target(self):
        node = _saved_query_node(self.team, DAG.get_or_create_default(self.team), "mv", NodeType.MAT_VIEW)
        set_declared_target(node, H6)
        assert node.saved_query is not None

        with mock.patch(f"{RECONCILE}.maybe_reconcile_dag"):
            apply_saved_query_frequency_target(node.saved_query, None, pinned=True, keep_target=True)

        node.refresh_from_db()
        self.assertEqual((get_declared_target(node), get_declared_pin(node)), (H6, True))

    def test_a_pin_on_its_own_is_refused_when_the_node_has_no_target(self):
        node = _saved_query_node(self.team, DAG.get_or_create_default(self.team), "mv", NodeType.MAT_VIEW)
        assert node.saved_query is not None

        with mock.patch(f"{RECONCILE}.maybe_reconcile_dag"), self.assertRaises(ValueError):
            apply_saved_query_frequency_target(node.saved_query, None, pinned=True, keep_target=True)

        node.refresh_from_db()
        self.assertFalse(get_declared_pin(node))

    def test_reconcile_failure_never_raises_past_commit(self):
        dag = self._dag_with_target()
        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(side_effect=RuntimeError("temporal down"))),
            mock.patch(f"{RECONCILE}.capture_exception") as capture,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        capture.assert_called_once()


@pytest.mark.django_db
class TestPromoteDagViewNodesToMatview(BaseTest):
    def _backed(
        self, dag: DAG, name: str, node_type: str, *, with_table: bool = True, origin: str | None = None
    ) -> Node:
        node = _saved_query_node(self.team, dag, name, node_type)
        saved_query = node.saved_query
        assert saved_query is not None
        saved_query.is_materialized = True
        if with_table:
            saved_query.table = DataWarehouseTable.objects.create(team=self.team, name=f"{name}_tbl", format="Delta")
        if origin is not None:
            saved_query.origin = origin
        saved_query.save()
        return node

    def test_retypes_only_the_view_nodes_that_materialize(self) -> None:
        dag = DAG.get_or_create_default(self.team)
        stranded = self._backed(dag, "stranded", NodeType.VIEW)
        endpoint = self._backed(dag, "endpoint_backed", NodeType.ENDPOINT)
        ephemeral = _saved_query_node(self.team, dag, "ephemeral", NodeType.VIEW)
        # A backing table that went away nulls table_id and leaves the intent behind. This is the
        # node that used to stay a view forever, so it could never get its table back.
        lost_its_table = self._backed(dag, "lost_its_table", NodeType.VIEW, with_table=False)

        assert promote_dag_view_nodes_to_matview(dag) == 2

        for node in (stranded, endpoint, ephemeral, lost_its_table):
            node.refresh_from_db()
        assert stranded.type == NodeType.MAT_VIEW
        assert lost_its_table.type == NodeType.MAT_VIEW
        # Nobody asked for this one to materialize, so it is a real ephemeral view.
        assert ephemeral.type == NodeType.VIEW
        assert endpoint.type == NodeType.ENDPOINT

    def test_a_managed_view_is_promoted_on_its_table_not_its_flag(self) -> None:
        # Revenue Analytics sets is_materialized when it provisions a view, before anything runs,
        # so the flag there is not a request to materialize and many carry it untruthfully.
        dag = DAG.get_or_create_default(self.team)
        never_ran = self._backed(
            dag,
            "managed_never_ran",
            NodeType.VIEW,
            with_table=False,
            origin=DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET,
        )
        has_run = self._backed(
            dag, "managed_has_run", NodeType.VIEW, origin=DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET
        )

        assert promote_dag_view_nodes_to_matview(dag) == 1

        never_ran.refresh_from_db()
        has_run.refresh_from_db()
        assert never_ran.type == NodeType.VIEW
        assert has_run.type == NodeType.MAT_VIEW

    def test_conversion_to_tiers_repairs_stranded_nodes(self):
        dag = DAG.get_or_create_default(self.team)
        stranded = self._backed(dag, "stranded", NodeType.VIEW)
        set_declared_target(stranded, M15)

        with (
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
    def test_deletes_the_schedules_of_every_dag_of_the_team(self):
        dag = DAG.objects.create(team=self.team, name="Default")

        with mock.patch(
            f"{RECONCILE}.delete_dag_schedules",
            return_value=DagScheduleTeardown(ok=True, deleted=(str(dag.id),)),
        ) as delete_dag:
            delete_team_data_modeling_schedules(self.team.id)

        delete_dag.assert_called_once_with(str(dag.id))

    def test_raises_when_a_dag_teardown_fails_so_the_activity_retries(self):
        DAG.objects.create(team=self.team, name="Default")

        with mock.patch(
            f"{RECONCILE}.delete_dag_schedules",
            return_value=DagScheduleTeardown(ok=False, deleted=()),
        ):
            with pytest.raises(TeamScheduleTeardownError):
                delete_team_data_modeling_schedules(self.team.id)
