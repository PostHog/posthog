from datetime import timedelta

from posthog.test.base import BaseTest

from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.logic.tier_run_report import (
    BLOCKED,
    FAILED,
    MISSING,
    NOT_MATERIALIZING,
    OK,
    SUSPENDED,
    build_tier_runs,
    untargeted_nodes,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.data_modeling_job import DataModelingJob, DataModelingJobStatus
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.test.helpers import saved_query_node, table_node

DAILY = timedelta(days=1)
HOURLY = timedelta(hours=1)


class TestTierRunReport(BaseTest):
    def setUp(self):
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name="Default")

    def _node(self, name: str, target: timedelta | None, node_type: str = NodeType.MAT_VIEW) -> Node:
        node = saved_query_node(self.team, self.dag, name, node_type)
        if target is not None:
            set_declared_target(node, target)
            node.save()
        return node

    def _job(self, node: Node, *, parent_workflow_id: str, status: str, error: str | None = None) -> DataModelingJob:
        return DataModelingJob.objects.create(
            team=self.team,
            saved_query=node.saved_query,
            status=status,
            error=error,
            parent_workflow_id=parent_workflow_id,
            workflow_id=f"materialize-view-{self.dag.id}-{node.id}-2026-07-25T03:00:00+00:00",
            workflow_run_id=f"run-{node.id}",
        )

    def _daily_parent(self, at: str = "2026-07-25T03:00:00Z") -> str:
        return f"execute-dag-{self.dag.id}:86400-{at}"

    def test_classifies_every_outcome_of_the_last_tier_run(self):
        # the shape a real daily run produces: some nodes materialize, some fail, and the rest
        # never get a job for three very different reasons that must not be conflated
        ok = self._node("ok_model", DAILY)
        failed = self._node("failed_model", DAILY)
        blocked = self._node("blocked_model", DAILY)
        suspended = self._node("suspended_model", DAILY)
        self._node("missing_model", DAILY)
        self._node("view_model", DAILY, node_type=NodeType.VIEW)

        Edge.objects.create(team=self.team, dag=self.dag, source=failed, target=blocked)
        suspended.properties["system"]["suspended"] = {"clickhouse": {"reason": "Workflow was cancelled"}}
        suspended.save()

        parent = self._daily_parent()
        self._job(ok, parent_workflow_id=parent, status=DataModelingJobStatus.COMPLETED)
        self._job(failed, parent_workflow_id=parent, status=DataModelingJobStatus.FAILED, error="boom\nsecond line")

        (tier,) = build_tier_runs(self.dag)

        assert tier.label == "1day"
        assert tier.schedule_id == f"{self.dag.id}:86400"
        assert tier.parent_workflow_id == parent
        assert {node.name: node.status for node in tier.nodes} == {
            "ok_model": OK,
            "failed_model": FAILED,
            "blocked_model": BLOCKED,
            "suspended_model": SUSPENDED,
            "missing_model": MISSING,
            "view_model": NOT_MATERIALIZING,
        }
        # 5 materializing nodes declared, only 2 produced a job
        assert (tier.declared, tier.ran) == (5, 2)
        assert not tier.is_clean

        by_name = {node.name: node for node in tier.nodes}
        assert by_name["failed_model"].detail == "boom"
        assert "Workflow was cancelled" in by_name["suspended_model"].detail
        assert "failed_model" in by_name["blocked_model"].detail
        assert by_name["ok_model"].workflow_run_id == f"run-{ok.id}"

    def test_reports_only_the_most_recent_run_of_the_tier(self):
        # an earlier run's failure must not be reported as the current state
        node = self._node("model", DAILY)
        self._job(
            node,
            parent_workflow_id=self._daily_parent("2026-07-24T03:00:00Z"),
            status=DataModelingJobStatus.FAILED,
            error="yesterday",
        )
        self._job(node, parent_workflow_id=self._daily_parent(), status=DataModelingJobStatus.COMPLETED)

        (tier,) = build_tier_runs(self.dag)

        assert tier.parent_workflow_id == self._daily_parent()
        assert [node.status for node in tier.nodes] == [OK]

    def test_a_job_from_another_tier_does_not_count_as_this_tier_running(self):
        # the same saved query can materialize under a different cadence; attributing that job
        # here would report a tier as healthy when its own schedule never fired
        node = self._node("model", DAILY)
        self._job(
            node,
            parent_workflow_id=f"execute-dag-{self.dag.id}:3600-2026-07-25T04:00:00Z",
            status=DataModelingJobStatus.COMPLETED,
        )

        (tier,) = build_tier_runs(self.dag)

        assert tier.parent_workflow_id is None
        assert [node.status for node in tier.nodes] == [MISSING]

    def test_tiers_are_ordered_by_cadence_and_split_by_target(self):
        self._node("hourly_model", HOURLY)
        self._node("daily_model", DAILY)

        tiers = build_tier_runs(self.dag)

        assert [tier.label for tier in tiers] == ["1hour", "1day"]
        assert [[node.name for node in tier.nodes] for tier in tiers] == [["hourly_model"], ["daily_model"]]

    def test_untargeted_nodes_are_reported_outside_every_tier(self):
        table_node(self.team, self.dag, "source_table", {})
        self._node("targeted", DAILY)
        stray = self._node("no_target", None)

        (tier,) = build_tier_runs(self.dag)

        assert [node.name for node in tier.nodes] == ["targeted"]
        assert {node.name for node in untargeted_nodes(self.dag)} == {"source_table", stray.name}
