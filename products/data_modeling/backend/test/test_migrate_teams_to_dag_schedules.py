from datetime import timedelta
from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

import temporalio.service

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.node_frequency import get_declared_target
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.test.helpers import temporal_listing as _temporal_listing

M15 = timedelta(minutes=15)
DAY = timedelta(hours=24)

RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"
COMMAND = "products.data_modeling.backend.management.commands.migrate_teams_to_dag_schedules"


@pytest.mark.django_db
class TestMigrateTeamsToDagSchedulesTiered(BaseTest):
    def _v1_dag_with_mixed_frequencies(self):
        dag = DAG.objects.create(team=self.team, name="Default")
        nodes = {}
        for name, interval in (("fast", M15), ("slow", DAY)):
            saved_query = DataWarehouseSavedQuery.objects.create(
                name=name,
                team=self.team,
                query={"query": "SELECT 1", "kind": "HogQLQuery"},
                sync_frequency_interval=interval,
            )
            nodes[name] = Node.objects.create(team=self.team, dag=dag, saved_query=saved_query, type=NodeType.VIEW)
        return dag, nodes

    def _run(self, existing_schedule_ids, delete_side_effect=None):
        create = mock.AsyncMock()
        update = mock.AsyncMock()
        v1_delete = mock.Mock(side_effect=delete_side_effect)
        with (
            mock.patch(f"{COMMAND}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{COMMAND}.sync_connect", return_value=mock.Mock()),
            mock.patch(f"{RECONCILE}.delete_schedule", v1_delete),
            mock.patch(
                f"{RECONCILE}.async_connect",
                new=mock.AsyncMock(return_value=_temporal_listing(existing_schedule_ids)),
            ),
            mock.patch(f"{RECONCILE}.a_create_schedule", create),
            mock.patch(f"{RECONCILE}.a_update_schedule", update),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()),
        ):
            call_command("migrate_teams_to_dag_schedules", "--team-ids", str(self.team.pk), stdout=StringIO())
        return create, update, v1_delete

    def test_mixed_frequencies_migrate_to_separate_tiers(self):
        # the single-schedule migration refused mixed-frequency DAGs entirely; tiers are the point
        dag, nodes = self._v1_dag_with_mixed_frequencies()

        create, _update, v1_delete = self._run(existing_schedule_ids=[])

        created_ids = {call.kwargs["id"] for call in create.call_args_list}
        self.assertEqual(created_ids, {tier_schedule_id(str(dag.id), M15), tier_schedule_id(str(dag.id), DAY)})
        self.assertEqual(v1_delete.call_count, 2)

        # targets persisted from the v1 intervals; intervals nulled once consumed
        for name, interval in (("fast", M15), ("slow", DAY)):
            node = nodes[name]
            node.refresh_from_db()
            self.assertEqual(get_declared_target(node), interval)
            assert node.saved_query is not None
            node.saved_query.refresh_from_db()
            self.assertIsNone(node.saved_query.sync_frequency_interval)

    def test_rerun_converges_instead_of_no_opping(self):
        # the old command's cleanup was nested in the schedule-creation branch, so re-runs on
        # half-migrated DAGs did nothing forever
        dag, nodes = self._v1_dag_with_mixed_frequencies()
        tier_ids = [tier_schedule_id(str(dag.id), M15), tier_schedule_id(str(dag.id), DAY)]
        not_found = temporalio.service.RPCError("not found", temporalio.service.RPCStatusCode.NOT_FOUND, b"")

        create, update, v1_delete = self._run(existing_schedule_ids=tier_ids, delete_side_effect=not_found)

        create.assert_not_called()
        self.assertEqual({call.kwargs["id"] for call in update.call_args_list}, set(tier_ids))
        self.assertEqual(v1_delete.call_count, 2)
        for node in nodes.values():
            assert node.saved_query is not None
            node.saved_query.refresh_from_db()
            self.assertIsNone(node.saved_query.sync_frequency_interval)

    def test_transient_v1_delete_failure_keeps_interval_for_retry(self):
        # a transient (non-NOT_FOUND) delete failure must keep that query's interval so a re-run
        # retries, instead of orphaning a v1 schedule beside the tiers
        dag, nodes = self._v1_dag_with_mixed_frequencies()
        assert nodes["fast"].saved_query is not None
        failed_id = str(nodes["fast"].saved_query.id)
        transient = temporalio.service.RPCError("boom", temporalio.service.RPCStatusCode.UNAVAILABLE, b"")

        def delete(_temporal, *, schedule_id):
            if schedule_id == failed_id:
                raise transient

        self._run(existing_schedule_ids=[], delete_side_effect=delete)

        for name in ("fast", "slow"):
            assert nodes[name].saved_query is not None
            nodes[name].saved_query.refresh_from_db()
        # failed delete keeps its interval (retryable); the successful one is cleared
        self.assertEqual(nodes["fast"].saved_query.sync_frequency_interval, M15)
        self.assertIsNone(nodes["slow"].saved_query.sync_frequency_interval)

    def test_query_in_two_dags_keeps_its_own_interval(self):
        # a saved query with nodes in two of the team's DAGs must seed both from its own interval;
        # nulling the shared interval per DAG mid-migration would leave the second node to re-seed
        # from the DAG's 1-day default — a silent freshness regression
        shared = DataWarehouseSavedQuery.objects.create(
            name="shared",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=M15,
        )
        dag_a = DAG.objects.create(team=self.team, name="A", sync_frequency_interval=DAY)
        dag_b = DAG.objects.create(team=self.team, name="B", sync_frequency_interval=DAY)
        node_a = Node.objects.create(team=self.team, dag=dag_a, saved_query=shared, type=NodeType.VIEW)
        node_b = Node.objects.create(team=self.team, dag=dag_b, saved_query=shared, type=NodeType.VIEW)

        self._run(existing_schedule_ids=[])

        node_a.refresh_from_db()
        node_b.refresh_from_db()
        self.assertEqual(get_declared_target(node_a), M15)
        self.assertEqual(get_declared_target(node_b), M15)
        shared.refresh_from_db()
        self.assertIsNone(shared.sync_frequency_interval)

    def test_temporal_outage_in_sweep_does_not_abort_the_run(self):
        # a connect failure during phase 2 must skip this team's v1 sweep (idempotent on re-run),
        # not propagate out and abort the whole fleet run before later teams are processed
        dag, nodes = self._v1_dag_with_mixed_frequencies()

        with (
            mock.patch(f"{COMMAND}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{COMMAND}.sync_connect", side_effect=RuntimeError("temporal down")),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_temporal_listing([]))),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()),
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()),
        ):
            # completes without raising — the outage is swallowed per team
            call_command("migrate_teams_to_dag_schedules", "--team-ids", str(self.team.pk), stdout=StringIO())

        # phase 1 still seeded the targets; phase 2 was skipped, so intervals stay for the re-run
        for name, interval in (("fast", M15), ("slow", DAY)):
            node = nodes[name]
            node.refresh_from_db()
            self.assertEqual(get_declared_target(node), interval)
            assert node.saved_query is not None
            node.saved_query.refresh_from_db()
            self.assertEqual(node.saved_query.sync_frequency_interval, interval)

    def test_flag_off_keeps_single_schedule_migration(self):
        dag, _nodes = self._v1_dag_with_mixed_frequencies()

        with (
            mock.patch(f"{COMMAND}.tiered_schedules_enabled", return_value=False),
            mock.patch(f"{COMMAND}.sync_connect", return_value=mock.Mock()),
            mock.patch(f"{COMMAND}.schedule_exists", return_value=False),
            mock.patch(f"{COMMAND}.create_schedule") as create,
            mock.patch(f"{RECONCILE}.delete_schedule"),
        ):
            call_command("migrate_teams_to_dag_schedules", "--team-ids", str(self.team.pk), stdout=StringIO())

        # mixed frequencies are still refused on the legacy path — no schedule created
        create.assert_not_called()
        self.assertTrue(DAG.objects.filter(id=dag.id).exists())
