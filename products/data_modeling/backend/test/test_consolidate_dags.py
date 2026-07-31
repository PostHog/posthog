import uuid
from contextlib import contextmanager
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized
from temporalio.client import ScheduleListActionStartWorkflow

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.node_frequency import get_declared_target, set_declared_target
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models.dag import DAG, REVENUE_ANALYTICS_DAG_NAME
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType

M15 = timedelta(minutes=15)
H6 = timedelta(hours=6)

COMMAND = "products.data_modeling.backend.management.commands.consolidate_dags"
RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"


def _listing_client(schedules_by_dag):
    # query-aware fake: schedule listings are per-DAG (PostHogDagId search attribute), and the
    # command lists the target, each source, and the reconcile path — they must not see each
    # other's schedules
    def _listing(schedule_id):
        action = mock.Mock(spec=ScheduleListActionStartWorkflow, workflow="data-modeling-execute-dag")
        return mock.Mock(id=schedule_id, schedule=mock.Mock(action=action))

    async def fake_list_schedules(*_args, query="", **_kwargs):
        dag_id = query.split("'")[1] if "'" in query else ""

        async def gen():
            for schedule_id in schedules_by_dag.get(dag_id, []):
                yield _listing(schedule_id)

        return gen()

    client = mock.Mock()
    client.list_schedules = fake_list_schedules
    return client


@contextmanager
def _temporal_boundary(schedules_by_dag=None, v2_delete_error=None):
    v2_delete = mock.Mock()
    if v2_delete_error is not None:
        v2_delete.side_effect = v2_delete_error
    with (
        mock.patch(f"{COMMAND}.sync_connect"),
        mock.patch(f"{COMMAND}.delete_schedule", v2_delete),
        mock.patch(f"{RECONCILE}.delete_schedule") as v1_delete,
        mock.patch(
            f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_listing_client(schedules_by_dag or {}))
        ),
        mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as tier_create,
        mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as tier_update,
        mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()),
    ):
        yield SimpleNamespace(
            v1_delete=v1_delete, v2_delete=v2_delete, tier_create=tier_create, tier_update=tier_update
        )


@pytest.mark.django_db
class TestConsolidateDags(BaseTest):
    def _query(self, name: str, sql: str, interval: timedelta | None = None) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            name=name, team=self.team, query={"query": sql, "kind": "HogQLQuery"}, sync_frequency_interval=interval
        )

    def _node(self, dag: DAG, saved_query: DataWarehouseSavedQuery) -> Node:
        return Node.objects.create(team=self.team, dag=dag, saved_query=saved_query, type=NodeType.MAT_VIEW)

    def _run(self, *args: str, apply: bool = False) -> str:
        out = StringIO()
        err = StringIO()
        flags = ["--apply"] if apply else []
        call_command("consolidate_dags", "--team-id", str(self.team.pk), *flags, *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_end_to_end_shared_dropped_unique_moved_with_rebuilt_edges(self):
        # The moved query depends on the dropped one, so its edges must rebuild against the
        # target's existing copy; the source DAG and both its nodes must be gone afterwards.
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        shared = self._query("shared_mv", "SELECT 1")
        target_shared_node = self._node(target, shared)
        self._node(source, shared)
        moved = self._query("only_in_source", "SELECT * FROM shared_mv")
        self._node(source, moved)

        with _temporal_boundary():
            output = self._run(apply=True)

        self.assertFalse(DAG.objects.filter(id=source.id).exists())
        moved_node = Node.objects.get(dag=target, saved_query=moved)
        self.assertTrue(Edge.objects.filter(dag=target, source=target_shared_node, target=moved_node).exists())
        self.assertEqual(Node.objects.filter(saved_query=shared).count(), 1)
        self.assertEqual(Node.objects.filter(saved_query=moved).count(), 1)
        self.assertIn("moved only_in_source", output)
        self.assertIn("dropped duplicate shared_mv", output)
        self.assertIn("deleted source DAG", output)

    def test_moves_sync_in_dependency_order(self):
        # dep_child depends on dep_parent, both only in the source: syncing the child first would
        # fail dependency resolution in the target (Node.DoesNotExist) and keep the source DAG.
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        parent = self._query("dep_parent", "SELECT * FROM events")
        child = self._query("dep_child", "SELECT * FROM dep_parent")
        parent_node = self._node(source, parent)
        child_node = self._node(source, child)
        Edge.objects.create(team=self.team, dag=source, source=parent_node, target=child_node)

        with _temporal_boundary():
            self._run(apply=True)

        self.assertFalse(DAG.objects.filter(id=source.id).exists())
        new_parent = Node.objects.get(dag=target, saved_query=parent)
        new_child = Node.objects.get(dag=target, saved_query=child)
        self.assertTrue(Edge.objects.filter(dag=target, source=new_parent, target=new_child).exists())
        events = Node.objects.get(dag=target, name="events", type=NodeType.TABLE)
        self.assertTrue(Edge.objects.filter(dag=target, source=events, target=new_parent).exists())

    @parameterized.expand(
        [
            ("tiered", "tier", True, True),
            ("legacy_v2", "legacy", True, False),
            ("v1_only", "none", False, False),
        ]
    )
    def test_target_schedule_mode_controls_teardown(self, _name, existing_kind, expect_sweep, expect_reconcile):
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        shared = self._query("shared_mv", "SELECT 1", interval=H6)
        self._node(target, shared)
        self._node(source, shared)
        moved = self._query("only_in_source", "SELECT * FROM events", interval=H6)
        self._node(source, moved)

        tier_id = tier_schedule_id(str(target.id), H6)
        schedules_by_dag = {
            "tier": {str(target.id): [tier_id]},
            "legacy": {str(target.id): [str(target.id)]},
            "none": {},
        }[existing_kind]

        with _temporal_boundary(schedules_by_dag=schedules_by_dag) as mocks:
            self._run(apply=True)

        self.assertFalse(DAG.objects.filter(id=source.id).exists())
        moved.refresh_from_db()
        shared.refresh_from_db()
        moved_node = Node.objects.get(dag=target, saved_query=moved)
        if expect_sweep:
            swept = {call.kwargs["schedule_id"] for call in mocks.v1_delete.call_args_list}
            self.assertEqual(swept, {str(moved.id), str(shared.id)})
            self.assertIsNone(moved.sync_frequency_interval)
            self.assertIsNone(shared.sync_frequency_interval)
            # cadence intent survives the nulled interval as a declared node target
            self.assertEqual(get_declared_target(moved_node), H6)
        else:
            mocks.v1_delete.assert_not_called()
            self.assertEqual(moved.sync_frequency_interval, H6)
            self.assertEqual(shared.sync_frequency_interval, H6)
            self.assertIsNone(get_declared_target(moved_node))
        if expect_reconcile:
            mocks.tier_update.assert_called_once()
            self.assertEqual(mocks.tier_update.call_args.kwargs["id"], tier_id)
            mocks.tier_create.assert_not_called()
        else:
            mocks.tier_update.assert_not_called()
            mocks.tier_create.assert_not_called()

    def test_refuses_v2_scheduled_source_when_target_is_v1_only(self):
        # moving these queries would strand them: their execute-dag schedules die with the source
        # DAG but a v1-only target has no schedule to hand coverage to
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        moved = self._query("only_in_source", "SELECT 1", interval=H6)
        self._node(source, moved)

        with _temporal_boundary(schedules_by_dag={str(source.id): [str(source.id)]}) as mocks:
            with self.assertRaisesRegex(CommandError, "v2-scheduled"):
                self._run(apply=True)

        self.assertTrue(DAG.objects.filter(id=source.id).exists())
        self.assertFalse(Node.objects.filter(dag=target, saved_query=moved).exists())
        moved.refresh_from_db()
        self.assertEqual(moved.sync_frequency_interval, H6)
        mocks.v1_delete.assert_not_called()
        mocks.v2_delete.assert_not_called()

    def test_rerun_finalizes_target_after_crashed_run(self):
        # a prior run that crashed after deleting its source DAGs leaves a moved query on the
        # target with its interval intact, no declared target, and a live v1 schedule; a plain
        # re-run must finish seed/sweep/null/reconcile from the target's own state
        target = DAG.get_or_create_default(self.team)
        stranded = self._query("stranded_mv", "SELECT 1", interval=H6)
        node = self._node(target, stranded)
        tier_id = tier_schedule_id(str(target.id), H6)

        with _temporal_boundary(schedules_by_dag={str(target.id): [tier_id]}) as mocks:
            self._run(apply=True)

        node.refresh_from_db()
        stranded.refresh_from_db()
        self.assertEqual(get_declared_target(node), H6)
        self.assertIsNone(stranded.sync_frequency_interval)
        swept = {call.kwargs["schedule_id"] for call in mocks.v1_delete.call_args_list}
        self.assertEqual(swept, {str(stranded.id)})
        mocks.tier_update.assert_called_once()
        self.assertEqual(mocks.tier_update.call_args.kwargs["id"], tier_id)

    def test_source_dag_interval_carries_as_declared_target(self):
        # Legacy-migrated source shape: query intervals nulled, cadence lives only on
        # dag.sync_frequency_interval. The finalize seeds from the *target* DAG, whose interval is
        # NULL here, so unless the source cadence is captured at plan time the moved query arrives
        # with no effective cadence and reconcile drops it from every tier.
        target = DAG.get_or_create_default(self.team)
        target.sync_frequency_interval = None
        target.save()
        source = DAG.objects.create(team=self.team, name="posthog_team", sync_frequency_interval=H6)
        moved = self._query("only_in_source", "SELECT 1")
        self._node(source, moved)
        tier_id = tier_schedule_id(str(target.id), H6)

        with _temporal_boundary(schedules_by_dag={str(target.id): [tier_id], str(source.id): [str(source.id)]}):
            self._run(apply=True)

        self.assertFalse(DAG.objects.filter(id=source.id).exists())
        moved_node = Node.objects.get(dag=target, saved_query=moved)
        self.assertEqual(get_declared_target(moved_node), H6)

    def test_finalize_redetects_target_mode_after_mid_run_conversion(self):
        # The pre-flight check sees a v1-only target; a concurrent reconcile converts it to tiers
        # before the finalize. Acting on the stale snapshot would skip the seed/sweep/reconcile and
        # leave the moved query double-scheduled (v1 + tier).
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        moved = self._query("only_in_source", "SELECT 1", interval=H6)
        self._node(source, moved)
        tier_id = tier_schedule_id(str(target.id), H6)

        target_listings = iter([set(), {tier_id}])

        def fake_listing(dag_id):
            if dag_id == str(target.id):
                return next(target_listings)
            return set()

        with (
            _temporal_boundary(schedules_by_dag={str(target.id): [tier_id]}) as mocks,
            mock.patch(f"{COMMAND}.list_existing_schedule_ids", side_effect=fake_listing),
        ):
            self._run(apply=True)

        moved.refresh_from_db()
        self.assertIsNone(moved.sync_frequency_interval)
        swept = {call.kwargs["schedule_id"] for call in mocks.v1_delete.call_args_list}
        self.assertEqual(swept, {str(moved.id)})
        mocks.tier_update.assert_called_once()
        self.assertEqual(get_declared_target(Node.objects.get(dag=target, saved_query=moved)), H6)

    def test_failed_move_keeps_source_dag_and_raises(self):
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        good = self._query("good_view", "SELECT 1")
        bad = self._query("bad_view", "SELECT * FROM nonexistent_table_xyz")
        self._node(source, good)
        self._node(source, bad)

        with _temporal_boundary() as mocks:
            with self.assertRaisesRegex(CommandError, "incomplete"):
                self._run(apply=True)

        # the DAG survives so the failed query's only node is not destroyed; the successful move
        # remains in the target as a duplicate a re-run classifies as DROP
        self.assertTrue(DAG.objects.filter(id=source.id).exists())
        self.assertTrue(Node.objects.filter(dag=source, saved_query=bad).exists())
        self.assertTrue(Node.objects.filter(dag=target, saved_query=good).exists())
        mocks.v2_delete.assert_not_called()

    def test_adopt_unresolvable_lands_broken_query_edge_less_and_deletes_source_dag(self):
        # One broken query must not hold the team's consolidation hostage: with the flag, the
        # unresolvable query is adopted into the target with no edges and a marker, cadence intent
        # intact, while healthy queries move normally and the source DAG is deleted.
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        good = self._query("good_view", "SELECT * FROM events")
        bad = self._query("bad_view", "SELECT * FROM nonexistent_table_xyz")
        self._node(source, good)
        set_declared_target(self._node(source, bad), M15)

        with _temporal_boundary():
            output = self._run("--adopt-unresolvable", apply=True)

        self.assertFalse(DAG.objects.filter(id=source.id).exists())
        adopted = Node.objects.get(dag=target, saved_query=bad)
        self.assertFalse(Edge.objects.filter(dag=target, target=adopted).exists())
        self.assertIn("nonexistent_table_xyz", adopted.properties["system"]["degraded_sync"]["error"])
        self.assertEqual(get_declared_target(adopted), M15)
        good_node = Node.objects.get(dag=target, saved_query=good)
        events = Node.objects.get(dag=target, name="events", type=NodeType.TABLE)
        self.assertTrue(Edge.objects.filter(dag=target, source=events, target=good_node).exists())
        self.assertIn("adopted bad_view without edges", output)

    def test_adopted_node_unblocks_its_dependents_moves(self):
        # The reason the flag exists: one unresolvable query must not cascade into N failed
        # moves. Parent in a managed DAG (excluded from consolidation) → dependent fails
        # Node.DoesNotExist and is adopted edge-less → the dependent's own dependent resolves
        # the adopted node in the target and moves with a real edge.
        target = DAG.get_or_create_default(self.team)
        managed = DAG.get_or_create_revenue_analytics(self.team)
        managed_parent = self._query("stripe_view", "SELECT 1")
        self._node(managed, managed_parent)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        blocked = self._query("blocked_view", "SELECT * FROM stripe_view")
        dependent = self._query("dependent_view", "SELECT * FROM blocked_view")
        blocked_node = self._node(source, blocked)
        dependent_node = self._node(source, dependent)
        Edge.objects.create(team=self.team, dag=source, source=blocked_node, target=dependent_node)

        with _temporal_boundary():
            output = self._run("--adopt-unresolvable", apply=True)

        self.assertFalse(DAG.objects.filter(id=source.id).exists())
        adopted = Node.objects.get(dag=target, saved_query=blocked)
        self.assertFalse(Edge.objects.filter(dag=target, target=adopted).exists())
        self.assertIn("degraded_sync", adopted.properties["system"])
        moved = Node.objects.get(dag=target, saved_query=dependent)
        self.assertTrue(Edge.objects.filter(dag=target, source=adopted, target=moved).exists())
        self.assertIn("adopted blocked_view without edges", output)
        self.assertIn("moved dependent_view", output)

    def test_adopt_unresolvable_does_not_adopt_non_resolution_failures(self):
        # The flag exists for SQL that cannot resolve. A sync that fails for operational reasons
        # (DB blip, programming error) must stay a failed move — adopting it would delete the
        # source DAG and report success on a query a plain retry would have moved intact.
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        moved = self._query("only_in_source", "SELECT 1")
        self._node(source, moved)

        with _temporal_boundary():
            with mock.patch(f"{COMMAND}.sync_saved_query_to_dag", side_effect=RuntimeError("db down")):
                with self.assertRaisesRegex(CommandError, "incomplete"):
                    self._run("--adopt-unresolvable", apply=True)

        self.assertTrue(DAG.objects.filter(id=source.id).exists())
        self.assertFalse(Node.objects.filter(dag=target, saved_query=moved).exists())

    def test_adoption_failure_rolls_back_the_node(self):
        # If the marker save fails after get_or_create committed the node, an unmarked edge-less
        # node would survive; the re-run would then classify the query as DROP instead of
        # retrying the move, stranding it without the marker forever. Create + mark must commit
        # or roll back together so the re-run sees a clean MOVE to retry.
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        bad = self._query("bad_view", "SELECT * FROM nonexistent_table_xyz")
        self._node(source, bad)

        real_save = Node.save

        def failing_marker_save(node, *args, **kwargs):
            if kwargs.get("update_fields") == ["properties"]:
                raise RuntimeError("connection lost")
            return real_save(node, *args, **kwargs)

        with _temporal_boundary():
            with mock.patch.object(Node, "save", autospec=True, side_effect=failing_marker_save):
                with self.assertRaisesRegex(CommandError, "incomplete"):
                    self._run("--adopt-unresolvable", apply=True)

        self.assertTrue(DAG.objects.filter(id=source.id).exists())
        self.assertFalse(Node.objects.filter(dag=target, saved_query=bad).exists())

    def test_degraded_sync_marker_cleared_when_query_resolves_again(self):
        # A stale marker after the customer fixes their SQL would make the post-fix re-sync sweep
        # (and any dashboard keyed on the marker) report a healthy node as degraded forever.
        target = DAG.get_or_create_default(self.team)
        fixed = self._query("fixed_view", "SELECT * FROM events")
        node = Node.objects.create(
            team=self.team,
            dag=target,
            saved_query=fixed,
            type=NodeType.VIEW,
            properties={"system": {"degraded_sync": {"error": "Unknown table", "at": "2026-07-30T00:00:00+00:00"}}},
        )

        sync_saved_query_to_dag(fixed, dag=target, reconcile=False)

        node.refresh_from_db()
        self.assertNotIn("system", node.properties)
        events = Node.objects.get(dag=target, name="events", type=NodeType.TABLE)
        self.assertTrue(Edge.objects.filter(dag=target, source=events, target=node).exists())

    def test_schedule_teardown_failure_keeps_source_dag(self):
        # deleting the DAG row before its execute-dag schedules are gone would orphan the
        # schedules forever (the row is the only pointer to them)
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        moved = self._query("only_in_source", "SELECT 1")
        self._node(source, moved)
        schedules_by_dag = {str(target.id): [str(target.id)], str(source.id): [str(source.id)]}

        with _temporal_boundary(schedules_by_dag=schedules_by_dag, v2_delete_error=RuntimeError("temporal down")):
            with self.assertRaisesRegex(CommandError, "incomplete"):
                self._run(apply=True)

        self.assertTrue(DAG.objects.filter(id=source.id).exists())
        self.assertTrue(Node.objects.filter(dag=target, saved_query=moved).exists())

    def test_dry_run_by_default_mutates_nothing(self):
        source = DAG.objects.create(team=self.team, name="posthog_team")
        target = DAG.get_or_create_default(self.team)
        shared = self._query("shared_mv", "SELECT 1", interval=H6)
        self._node(target, shared)
        self._node(source, shared)
        moved = self._query("only_in_source", "SELECT 1", interval=H6)
        self._node(source, moved)

        with _temporal_boundary() as mocks:
            output = self._run()

        self.assertIn("move 1, drop 1", output)
        self.assertIn("dry run", output)
        self.assertTrue(DAG.objects.filter(id=source.id).exists())
        self.assertFalse(Node.objects.filter(dag=target, saved_query=moved).exists())
        moved.refresh_from_db()
        self.assertEqual(moved.sync_frequency_interval, H6)
        mocks.v1_delete.assert_not_called()
        mocks.v2_delete.assert_not_called()

    def test_dry_run_reports_edge_impact(self):
        # An edge touching a moved node must be re-pointed to the target; an edge whose only
        # involved node is dropped is redundant against the target's existing edge.
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        shared = self._query("shared_mv", "SELECT 1")
        self._node(target, shared)
        dropped_node = self._node(source, shared)
        moved_node = self._node(source, self._query("only_in_source", "SELECT 1"))
        events = Node.objects.create(team=self.team, dag=source, name="events", type=NodeType.TABLE)
        Edge.objects.create(team=self.team, dag=source, source=events, target=moved_node)
        Edge.objects.create(team=self.team, dag=source, source=events, target=dropped_node)

        output = self._run()

        self.assertIn("edges to re-point (touch a moved node): 1", output)
        self.assertIn("edges to drop as redundant (only dropped nodes): 1", output)
        self.assertIn("edges to re-point: 1, edges to drop: 1", output)

    def test_duplicate_is_kept_when_the_claiming_dag_failed_to_move_it(self):
        # dag_a claims the shared query for MOVE and dag_b's copy is planned as a DROP. If dag_a's
        # move fails, dag_b's node is the last place that query's declared target exists — dropping
        # it and deleting dag_b would destroy the intent with only a "dropped duplicate" line.
        DAG.get_or_create_default(self.team)
        dag_a = DAG.objects.create(team=self.team, name="dag_a")
        dag_b = DAG.objects.create(team=self.team, name="dag_b")
        shared = self._query("shared_mv", "SELECT * FROM nonexistent_table_xyz")
        self._node(dag_a, shared)
        self._node(dag_b, shared)

        with _temporal_boundary():
            with self.assertRaisesRegex(CommandError, "incomplete"):
                self._run(apply=True)

        # dag_a could not move it, so dag_b's copy is the last node the query has anywhere
        self.assertTrue(DAG.objects.filter(id=dag_b.id).exists())
        self.assertTrue(Node.objects.filter(dag=dag_b, saved_query=shared).exists())

    def test_dag_default_cadence_seeds_a_moved_node_with_no_interval(self):
        # A query only ever scheduled by its DAG's default cadence has no interval of its own. The
        # finalize nulls every interval and then reconciles, so with no DAG-level fallback the moved
        # node arrives with nothing declared, gets no effective cadence, and is dropped from every
        # tier — it stops materializing with nothing left in Postgres or Temporal to show why.
        target = DAG.get_or_create_default(self.team)
        target.sync_frequency_interval = H6
        target.save()
        source = DAG.objects.create(team=self.team, name="posthog_team")
        moved = self._query("only_in_source", "SELECT 1")  # no interval of its own
        self._node(source, moved)

        tier_id = tier_schedule_id(str(target.id), H6)
        with _temporal_boundary(schedules_by_dag={str(target.id): [tier_id]}):
            self._run(apply=True)

        moved_node = Node.objects.get(dag=target, saved_query=moved)
        self.assertEqual(get_declared_target(moved_node), H6)

    def test_verbose_lists_query_names(self):
        # --verbose is how an operator confirms *which* queries move before committing to --apply
        # on live data, so the per-name listing has to actually appear behind the flag.
        DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        self._node(source, self._query("only_in_source", "SELECT 1"))

        self.assertNotIn("only_in_source", self._run())
        self.assertIn("move (in dependency order): only_in_source", self._run("--verbose"))

    def test_conflicting_freshness_targets_flagged(self):
        # Same query in two DAGs with different declared cadences: only one node survives the merge,
        # so the dry run must surface both copies for a human to pick the winner.
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        shared = self._query("conflicted", "SELECT 1")
        set_declared_target(self._node(target, shared), H6)
        set_declared_target(self._node(source, shared), M15)

        output = self._run()

        self.assertIn("freshness-target conflicts: 1", output)
        self.assertIn("⚠ conflicted:", output)
        self.assertIn("6hour", output)
        self.assertIn("15min", output)

    @parameterized.expand([("both_agree", H6, H6), ("one_unset", H6, None), ("both_unset", None, None)])
    def test_non_conflicting_freshness_targets_not_flagged(self, _name, target_a, target_b):
        # Unset means "no opinion", so a lone declared target wins cleanly — not a conflict.
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        shared = self._query("agreeing", "SELECT 1")
        a = self._node(target, shared)
        b = self._node(source, shared)
        if target_a is not None:
            set_declared_target(a, target_a)
        if target_b is not None:
            set_declared_target(b, target_b)

        self.assertIn("freshness-target conflicts: 0", self._run())

    @parameterized.expand(
        [
            ("default_preferred", "default"),
            ("largest_without_default", "largest"),
            ("explicit_wins", "explicit"),
        ]
    )
    def test_target_selection(self, _name, kind):
        if kind == "largest":
            small = DAG.objects.create(team=self.team, name="small")
            large = DAG.objects.create(team=self.team, name="large")
            self._node(small, self._query("a", "SELECT 1"))
            self._node(large, self._query("b", "SELECT 1"))
            self._node(large, self._query("c", "SELECT 1"))

            output = self._run()

            self.assertIn(f"Merge target: large ({large.id})", output)
            self.assertIn("largest DAG by node count", output)
            return

        default = DAG.get_or_create_default(self.team)
        other = DAG.objects.create(team=self.team, name="posthog_team")
        self._node(other, self._query("a", "SELECT 1"))

        if kind == "explicit":
            output = self._run("--target-dag-id", str(other.id))
            self.assertIn(f"Merge target: posthog_team ({other.id})", output)
            self.assertIn("chosen via --target-dag-id", output)
        else:
            output = self._run()
            self.assertIn(f"Merge target: Default ({default.id})", output)
            self.assertIn("canonical 'Default' DAG", output)

    def test_managed_dag_never_touched(self):
        target = DAG.get_or_create_default(self.team)
        managed = DAG.get_or_create_revenue_analytics(self.team)
        managed_query = self._query("stripe.prod.mrr_revenue_view", "SELECT 1")
        self._node(managed, managed_query)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        moved = self._query("only_in_source", "SELECT 1")
        self._node(source, moved)

        with _temporal_boundary():
            output = self._run(apply=True)

        self.assertIn(f"Excluding 1 system-managed DAG(s): {REVENUE_ANALYTICS_DAG_NAME}", output)
        self.assertTrue(DAG.objects.filter(id=managed.id).exists())
        self.assertTrue(Node.objects.filter(dag=managed, saved_query=managed_query).exists())
        self.assertFalse(DAG.objects.filter(id=source.id).exists())
        self.assertTrue(Node.objects.filter(dag=target, saved_query=moved).exists())

    @parameterized.expand(
        [
            ("managed_target", "managed"),
            ("unknown_target", "unknown"),
            ("not_a_uuid", "garbage"),
        ]
    )
    def test_bad_target_dag_id_errors_before_any_change(self, _name, kind):
        DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        self._node(source, self._query("only_in_source", "SELECT 1"))
        managed = DAG.get_or_create_revenue_analytics(self.team)
        target_id = {"managed": str(managed.id), "unknown": str(uuid.uuid4()), "garbage": "not-a-uuid"}[kind]

        with _temporal_boundary():
            with self.assertRaises(CommandError):
                self._run("--target-dag-id", target_id, apply=True)

        self.assertTrue(DAG.objects.filter(id=source.id).exists())

    @parameterized.expand([("two_sources", 2), ("three_sources", 3)])
    def test_query_in_several_source_dags_lands_exactly_once(self, _name: str, source_count: int):
        # `saved_query_unique_within_team_dag` means the query can only land once: the first source
        # moves it, every later one must drop. Three sources exercises a drop against a target that
        # already holds the node, which two sources never reaches.
        target = DAG.get_or_create_default(self.team)
        shared = self._query("shared_everywhere", "SELECT 1")
        sources = [DAG.objects.create(team=self.team, name=f"dag_{i}") for i in range(source_count)]
        for source in sources:
            self._node(source, shared)

        with _temporal_boundary():
            output = self._run(apply=True)

        self.assertFalse(DAG.objects.filter(id__in=[dag.id for dag in sources]).exists())
        self.assertEqual(Node.objects.filter(saved_query=shared).count(), 1)
        self.assertTrue(Node.objects.filter(dag=target, saved_query=shared).exists())
        self.assertIn(f"moved: 1, dropped: {source_count - 1}", output)

    @parameterized.expand(
        [
            ("moved_node_inherits", "move", None, M15),
            ("dropped_copies_onto_unset_target", "drop", None, M15),
            ("target_declared_wins", "drop", H6, H6),
        ]
    )
    def test_declared_target_carried_from_source(self, _name, kind, target_declared, expected):
        target = DAG.get_or_create_default(self.team)
        source = DAG.objects.create(team=self.team, name="posthog_team")
        saved_query = self._query("carried", "SELECT 1")
        if kind == "drop":
            target_node = self._node(target, saved_query)
            if target_declared is not None:
                set_declared_target(target_node, target_declared)
        source_node = self._node(source, saved_query)
        set_declared_target(source_node, M15)

        with _temporal_boundary():
            self._run(apply=True)

        node = Node.objects.get(dag=target, saved_query=saved_query)
        self.assertEqual(get_declared_target(node), expected)
