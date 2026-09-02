from datetime import timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_modeling.backend.logic.node_frequency import set_declared_anchor, set_declared_target
from products.data_modeling.backend.logic.tier_run_report import (
    BLOCKED,
    CANCELLED,
    FAILED,
    MISSING,
    NOT_MATERIALIZING,
    OK,
    RUNNING,
    SUSPENDED,
    build_tier_runs,
    untargeted_nodes,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
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

    def _suspend(self, node: Node, *, engine: str = "clickhouse", reason: str = "Workflow was cancelled") -> None:
        node.properties.setdefault("system", {}).setdefault("suspended", {})[engine] = {"reason": reason}
        node.save()

    def _job(
        self,
        node: Node,
        *,
        parent_workflow_id: str,
        status: str,
        error: str | None = None,
        engine: str = DataModelingJobEngine.CLICKHOUSE,
    ) -> DataModelingJob:
        return DataModelingJob.objects.create(
            team=self.team,
            saved_query=node.saved_query,
            status=status,
            error=error,
            engine=engine,
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
        self._suspend(suspended)

        parent = self._daily_parent()
        self._job(ok, parent_workflow_id=parent, status=DataModelingJobStatus.COMPLETED)
        self._job(failed, parent_workflow_id=parent, status=DataModelingJobStatus.FAILED, error="boom\nsecond line")

        (tier,) = build_tier_runs(self.dag)

        assert tier.label == "1day"
        assert tier.schedule_id == f"{self.dag.id}:86400"
        assert tier.parent_workflow_id == parent
        # ordered worst-first, which is what surfaces failures on a DAG with hundreds of nodes
        assert [(node.name, node.status) for node in tier.nodes] == [
            ("missing_model", MISSING),
            ("failed_model", FAILED),
            ("suspended_model", SUSPENDED),
            ("blocked_model", BLOCKED),
            ("view_model", NOT_MATERIALIZING),
            ("ok_model", OK),
        ]
        assert tier.counts == {
            MISSING: 1,
            FAILED: 1,
            CANCELLED: 0,
            SUSPENDED: 1,
            BLOCKED: 1,
            RUNNING: 0,
            NOT_MATERIALIZING: 1,
            OK: 1,
        }
        # 5 materializing nodes declared, only 2 produced a job
        assert (tier.declared, tier.ran) == (5, 2)

        by_name = {node.name: node for node in tier.nodes}
        assert by_name["failed_model"].detail == "boom"
        assert "Workflow was cancelled" in by_name["suspended_model"].detail
        assert "failed_model" in by_name["blocked_model"].detail
        assert by_name["ok_model"].workflow_run_id == f"run-{ok.id}"

    @parameterized.expand(
        [
            ("another tier's run", "execute-dag-{dag}:3600-2026-07-25T04:00:00Z"),
            ("the legacy DAG-wide run", "execute-dag-{dag}-2026-07-24T03:00:00Z"),
        ]
    )
    def test_a_job_outside_this_tiers_latest_run_is_not_evidence_it_ran(self, _name, parent_template):
        # this tier DID run, so no fallback is in play — a job filed under any other parent must not
        # make the node look materialized. Dropping the parent filter and keying jobs by saved query
        # alone would report the tier as healthy when its own schedule never touched this node.
        node = self._node("model", DAILY)
        other = self._node("other", DAILY)
        self._job(other, parent_workflow_id=self._daily_parent(), status=DataModelingJobStatus.COMPLETED)
        self._job(
            node,
            parent_workflow_id=parent_template.format(dag=self.dag.id),
            status=DataModelingJobStatus.COMPLETED,
        )

        (tier,) = build_tier_runs(self.dag)

        assert {n.name: n.status for n in tier.nodes}["model"] == MISSING

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

    def test_tiers_are_ordered_by_cadence_and_split_by_target(self):
        self._node("hourly_model", HOURLY)
        self._node("daily_model", DAILY)

        tiers = build_tier_runs(self.dag)

        assert [(tier.label, tier.seconds) for tier in tiers] == [("1hour", 3600), ("1day", 86400)]
        assert [[node.name for node in tier.nodes] for tier in tiers] == [["hourly_model"], ["daily_model"]]

    def test_an_anchored_cohort_reports_its_own_schedule_and_run(self):
        # an anchored cohort is its own Temporal schedule with a 3-segment id; grouping by bare
        # interval or prefix-matching the 2-segment id would report every anchored node MISSING
        # on exactly the DAGs an operator anchored for closest observation
        anchored = self._node("anchored_model", DAILY)
        set_declared_anchor(anchored, 1350)
        spread = self._node("spread_model", DAILY)
        anchored_parent = f"execute-dag-{self.dag.id}:86400:1350-2026-07-25T22:30:00Z"
        self._job(anchored, parent_workflow_id=anchored_parent, status=DataModelingJobStatus.COMPLETED)
        self._job(spread, parent_workflow_id=self._daily_parent(), status=DataModelingJobStatus.COMPLETED)

        spread_tier, anchored_tier = build_tier_runs(self.dag)

        assert anchored_tier.schedule_id == f"{self.dag.id}:86400:1350"
        assert anchored_tier.parent_workflow_id == anchored_parent
        assert [n.status for n in anchored_tier.nodes] == [OK]
        assert spread_tier.schedule_id == f"{self.dag.id}:86400"
        assert [(n.name, n.status) for n in spread_tier.nodes] == [("spread_model", OK)]
        assert spread_tier.slug != anchored_tier.slug

    def test_untargeted_nodes_are_reported_outside_every_tier(self):
        table_node(self.team, self.dag, "source_table", {})
        self._node("targeted", DAILY)
        stray = self._node("no_target", None)

        (tier,) = build_tier_runs(self.dag)

        assert [node.name for node in tier.nodes] == ["targeted"]
        assert {node.name for node in untargeted_nodes(self.dag)} == {"source_table", stray.name}

    @parameterized.expand(
        [
            (DataModelingJobStatus.COMPLETED, OK),
            (DataModelingJobStatus.FAILED, FAILED),
            (DataModelingJobStatus.RUNNING, RUNNING),
            (DataModelingJobStatus.CANCELLED, CANCELLED),
        ]
    )
    def test_only_a_completed_job_reports_the_node_as_materialized(self, job_status, expected):
        # jobs default to Running, and a preempted node is written Cancelled — reporting anything
        # but Completed as ok would paint exactly the failures this page exists to find as green
        node = self._node("model", DAILY)
        self._job(node, parent_workflow_id=self._daily_parent(), status=job_status)

        (tier,) = build_tier_runs(self.dag)

        assert [n.status for n in tier.nodes] == [expected]

    @parameterized.expand(
        [
            (NodeType.MAT_VIEW, MISSING, "declared on this tier but the run produced no job"),
            (NodeType.ENDPOINT, MISSING, "declared on this tier but the run produced no job"),
            (NodeType.VIEW, NOT_MATERIALIZING, "view node — a run marks it successful and materializes nothing"),
        ]
    )
    def test_node_type_decides_whether_a_run_was_even_expected(self, node_type, expected_status, expected_detail):
        # endpoints materialize on v2 DAGs just like matviews; views never do
        self._node("model", DAILY, node_type=node_type)

        (tier,) = build_tier_runs(self.dag)

        assert (tier.nodes[0].status, tier.nodes[0].detail) == (expected_status, expected_detail)

    @parameterized.expand([(None, "0 rows"), ("", "0 rows"), ("   ", "0 rows"), ("\n", "0 rows"), ("boom\nx", "boom")])
    def test_a_failed_job_shows_the_first_line_of_its_error_whatever_the_error_is(self, error, expected_detail):
        # a whitespace-only error used to raise IndexError, taking the whole page down
        node = self._node("model", DAILY)
        self._job(node, parent_workflow_id=self._daily_parent(), status=DataModelingJobStatus.FAILED, error=error)

        (tier,) = build_tier_runs(self.dag)

        assert (tier.nodes[0].status, tier.nodes[0].detail) == (FAILED, expected_detail)

    def test_falls_back_to_the_legacy_dag_wide_run_when_the_tier_has_none(self):
        # a DAG not yet reconciled onto tiers runs everything under `execute-dag-{dag_id}`, which no
        # tier prefix matches; without the fallback every node reports as never having run
        node = self._node("model", DAILY)
        legacy_parent = f"execute-dag-{self.dag.id}-2026-07-25T03:00:00Z"
        self._job(node, parent_workflow_id=legacy_parent, status=DataModelingJobStatus.COMPLETED)

        (tier,) = build_tier_runs(self.dag)

        assert tier.run_is_legacy is True
        assert tier.parent_workflow_id == legacy_parent
        assert [n.status for n in tier.nodes] == [OK]

    def test_a_tier_run_wins_over_an_older_legacy_run(self):
        node = self._node("model", DAILY)
        self._job(
            node,
            parent_workflow_id=f"execute-dag-{self.dag.id}-2026-07-24T03:00:00Z",
            status=DataModelingJobStatus.COMPLETED,
        )
        self._job(node, parent_workflow_id=self._daily_parent(), status=DataModelingJobStatus.FAILED, error="boom")

        (tier,) = build_tier_runs(self.dag)

        assert tier.run_is_legacy is False
        assert [n.status for n in tier.nodes] == [FAILED]

    def test_a_failure_blocks_descendants_at_any_depth(self):
        # execute_dag skips the whole cone below a failure, so stopping at direct children would
        # report grandchildren as unexplained and send the operator after the wrong node
        a, b, c = self._node("a", DAILY), self._node("b", DAILY), self._node("c", DAILY)
        Edge.objects.create(team=self.team, dag=self.dag, source=a, target=b)
        Edge.objects.create(team=self.team, dag=self.dag, source=b, target=c)
        self._job(a, parent_workflow_id=self._daily_parent(), status=DataModelingJobStatus.FAILED, error="boom")

        (tier,) = build_tier_runs(self.dag)
        by_name = {n.name: n for n in tier.nodes}

        assert (by_name["b"].status, by_name["c"].status) == (BLOCKED, BLOCKED)
        assert "a" in by_name["c"].detail

    def test_a_node_that_is_both_suspended_and_downstream_reports_its_own_suspension(self):
        # suspension is the actionable cause; naming an upstream instead sends the operator away
        upstream = self._node("upstream", DAILY)
        both = self._node("both", DAILY)
        Edge.objects.create(team=self.team, dag=self.dag, source=upstream, target=both)
        self._suspend(both, reason="its own reason")
        self._job(upstream, parent_workflow_id=self._daily_parent(), status=DataModelingJobStatus.FAILED, error="boom")

        (tier,) = build_tier_runs(self.dag)

        assert {n.name: n.status for n in tier.nodes}["both"] == SUSPENDED

    def test_a_node_suspended_in_another_tier_blocks_its_descendants_here(self):
        # execute_dag reads suspended_nodes for the whole DAG, so a suspension on the hourly tier
        # skips daily descendants; seeding blocks only from this tier would call them unexplained
        upstream = self._node("hourly_upstream", HOURLY)
        downstream = self._node("daily_downstream", DAILY)
        Edge.objects.create(team=self.team, dag=self.dag, source=upstream, target=downstream)
        self._suspend(upstream)

        _hourly, daily = build_tier_runs(self.dag)

        assert {n.name: n.status for n in daily.nodes}["daily_downstream"] == BLOCKED

    def test_a_node_rides_its_effective_cadence_tier_not_its_declared_one(self):
        # schedules bucket by effective cadence (min of own target and downstream, source-clamped),
        # so a declared-daily node above a 15min consumer runs under the 15min schedule; grouping
        # by declared target would look it up in a daily run that never contains it
        upstream = self._node("upstream_model", DAILY)
        consumer = self._node("consumer_model", timedelta(minutes=15))
        Edge.objects.create(team=self.team, dag=self.dag, source=upstream, target=consumer)
        parent = f"execute-dag-{self.dag.id}:900-2026-07-25T03:00:00Z"
        self._job(upstream, parent_workflow_id=parent, status=DataModelingJobStatus.COMPLETED)
        self._job(consumer, parent_workflow_id=parent, status=DataModelingJobStatus.COMPLETED)

        (tier,) = build_tier_runs(self.dag)

        assert tier.seconds == 900
        assert {n.name: n.status for n in tier.nodes} == {"upstream_model": OK, "consumer_model": OK}

    def test_only_the_serving_engine_counts_for_suspension_and_for_jobs(self):
        # the duckgres shadow suspends independently and writes its own job row; neither should
        # change what the clickhouse run is reported to have done
        shadow_suspended = self._node("shadow_suspended", DAILY)
        self._suspend(shadow_suspended, engine="duckgres", reason="shadow blew up")
        shadow_only = self._node("shadow_only", DAILY)
        served = self._node("served", DAILY)
        parent = self._daily_parent()
        self._job(shadow_only, parent_workflow_id=parent, status=DataModelingJobStatus.COMPLETED, engine="duckgres")
        self._job(served, parent_workflow_id=parent, status=DataModelingJobStatus.COMPLETED)

        (tier,) = build_tier_runs(self.dag)
        by_name = {n.name: n.status for n in tier.nodes}

        assert by_name["shadow_suspended"] == MISSING  # not "suspended" — the CH run still ran it
        assert by_name["shadow_only"] == MISSING  # a shadow job is not evidence the node materialized
        assert by_name["served"] == OK

    def test_a_soft_deleted_saved_query_leaves_no_phantom_row(self):
        # the scheduler excludes soft-deleted queries but the target stays on the node, so without
        # the same exclusion the node would report missing on every page load forever
        self._node("deleted_model", DAILY)
        DataWarehouseSavedQuery.objects.filter(team=self.team, name="deleted_model").update(deleted=True)
        self._node("live_model", DAILY)

        (tier,) = build_tier_runs(self.dag)

        assert [n.name for n in tier.nodes] == ["live_model"]
        assert [n.name for n in untargeted_nodes(self.dag)] == []

    def test_started_at_is_the_first_job_of_the_run_not_the_last(self):
        # children start over a long window on a wide DAG; the last one is not when the run began
        first, last = self._node("first", DAILY), self._node("last", DAILY)
        parent = self._daily_parent()
        first_job = self._job(first, parent_workflow_id=parent, status=DataModelingJobStatus.COMPLETED)
        self._job(last, parent_workflow_id=parent, status=DataModelingJobStatus.COMPLETED)

        (tier,) = build_tier_runs(self.dag)

        assert tier.started_at == first_job.created_at
