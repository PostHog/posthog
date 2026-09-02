import json
from datetime import timedelta
from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

from temporalio.service import RPCError, RPCStatusCode

from posthog.models.team import Team

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.node_frequency import get_declared_target, set_declared_target
from products.data_modeling.backend.management.commands.batch_reconcile_teams import REPORT_MARKER
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.test.helpers import temporal_listing as _temporal_listing

H6 = timedelta(hours=6)

RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"
BATCH = "products.data_modeling.backend.management.commands.batch_reconcile_teams"


@pytest.mark.django_db
class TestBatchReconcileTeams(BaseTest):
    def _legacy_dag(self, team) -> tuple[DAG, Node]:
        dag = DAG.objects.create(team=team, name="Default", sync_frequency_interval=H6)
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=f"v_{team.pk}",
            team=team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=H6,
        )
        node = Node.objects.create(team=team, dag=dag, saved_query=saved_query, type=NodeType.VIEW)
        return dag, node

    def _run(self, team_ids: str, *extra_args, existing=(), verify_listing=None):
        out = StringIO()
        with (
            mock.patch(f"{BATCH}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.delete_schedule"),
            mock.patch(
                f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_temporal_listing(list(existing)))
            ),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
            mock.patch(f"{BATCH}.async_connect", new=mock.AsyncMock()),
            mock.patch(
                f"{BATCH}.a_schedule_exists",
                new=mock.AsyncMock(side_effect=lambda _t, sid: sid in (verify_listing or set())),
            ),
        ):
            call_command("batch_reconcile_teams", "--team-ids", team_ids, *extra_args, stdout=out, stderr=StringIO())
        report = json.loads(out.getvalue().split(REPORT_MARKER, 1)[1])
        return report, create, delete

    def test_breaker_halts_batch_and_skips_remaining_teams(self):
        # an unsupported tier on the first team must stop the batch before the second team
        # is even planned, let alone applied
        dag_a, node_a = self._legacy_dag(self.team)
        set_declared_target(node_a, timedelta(minutes=7))
        node_a.save()
        team_b = Team.objects.create(organization=self.organization, name="second")
        dag_b, node_b = self._legacy_dag(team_b)

        report, create, _delete = self._run(f"{self.team.pk},{team_b.pk}", "--apply", existing=[str(dag_a.id)])

        assert report["halted"] is True
        assert "unsupported tier" in report["halt_reason"]
        statuses = {t["team_id"]: t["status"] for t in report["teams"]}
        assert statuses[self.team.pk] == "anomaly"
        assert statuses[team_b.pk] == "skipped"
        create.assert_not_called()
        node_b.refresh_from_db()
        assert get_declared_target(node_b) is None

    def test_apply_creates_planned_tier_and_verifies(self):
        dag, node = self._legacy_dag(self.team)
        legacy_id = str(dag.id)
        expected_tier = tier_schedule_id(legacy_id, H6)

        report, create, _delete = self._run(
            str(self.team.pk), "--apply", existing=[legacy_id], verify_listing={expected_tier}
        )

        assert report["halted"] is False
        team_record = report["teams"][0]
        assert team_record["status"] == "applied"
        assert team_record["dags"][0]["planned_tiers"] == [int(H6.total_seconds())]
        assert team_record["dags"][0]["verified"] is True
        create.assert_called_once()
        assert create.call_args.kwargs["id"] == expected_tier
        assert node.saved_query is not None
        node.saved_query.refresh_from_db()
        assert node.saved_query.sync_frequency_interval is None

    def test_verify_mismatch_halts(self):
        # if the live schedule set after apply is not exactly the planned tier set, the batch
        # must halt instead of reporting success
        dag, _node = self._legacy_dag(self.team)

        report, _create, _delete = self._run(str(self.team.pk), "--apply", existing=[str(dag.id)], verify_listing=set())

        assert report["halted"] is True
        assert "missing planned schedule" in report["halt_reason"]
        assert report["teams"][0]["status"] == "anomaly"

    def test_invalid_declared_targets_are_reported_but_do_not_halt(self):
        # pre-existing declared-target drift is fleet-common (team 2 alone has 18) and does not
        # affect scheduling correctness; halting on it would block the rollout
        from products.data_modeling.backend.models.edge import Edge

        dag, parent = self._legacy_dag(self.team)
        child_query = DataWarehouseSavedQuery.objects.create(
            name="child",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        child = Node.objects.create(team=self.team, dag=dag, saved_query=child_query, type=NodeType.VIEW)
        Edge.objects.create(team=self.team, dag=dag, source=parent, target=child)
        set_declared_target(parent, timedelta(days=1))
        parent.save()
        set_declared_target(child, timedelta(hours=1))
        child.save()

        report, _create, _delete = self._run(str(self.team.pk), existing=[str(dag.id)])

        assert report["halted"] is False
        team_record = report["teams"][0]
        assert team_record["status"] == "planned"
        invalid = team_record["dags"][0]["invalid_targets"]
        assert [t["node_id"] for t in invalid] == [str(parent.id)]
        assert invalid[0]["consumer_ceiling"] == int(timedelta(hours=1).total_seconds())

    def test_rate_limited_team_retries_instead_of_halting(self):
        # a temporal namespace rate limit mid-batch must back off and retry the team,
        # not halt the whole batch (halted a real 200-team production run)
        dag, _node = self._legacy_dag(self.team)
        listing = _temporal_listing([str(dag.id)])
        rate_limit = RPCError("namespace rate limit exceeded", RPCStatusCode.RESOURCE_EXHAUSTED, b"")

        out = StringIO()
        with (
            mock.patch(f"{BATCH}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{BATCH}.time.sleep") as sleep,
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.delete_schedule"),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(side_effect=[rate_limit, listing])),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()),
            mock.patch(f"{BATCH}.async_connect", new=mock.AsyncMock()),
            mock.patch(f"{BATCH}.a_schedule_exists", new=mock.AsyncMock(return_value=False)),
        ):
            call_command("batch_reconcile_teams", "--team-ids", str(self.team.pk), stdout=out, stderr=StringIO())
        report = json.loads(out.getvalue().split(REPORT_MARKER, 1)[1])

        assert report["halted"] is False
        assert report["teams"][0]["status"] == "planned"
        assert len(report["teams"][0]["dags"]) == 1
        sleep.assert_called_once_with(10)

    def test_plan_only_writes_nothing(self):
        dag, node = self._legacy_dag(self.team)

        report, create, delete = self._run(str(self.team.pk), existing=[str(dag.id)])

        assert report["halted"] is False
        assert report["teams"][0]["status"] == "planned"
        assert report["teams"][0]["dags"][0]["planned_tiers"] == [int(H6.total_seconds())]
        create.assert_not_called()
        delete.assert_not_called()
        node.refresh_from_db()
        assert get_declared_target(node) is None
        assert node.saved_query is not None
        node.saved_query.refresh_from_db()
        assert node.saved_query.sync_frequency_interval == H6
