from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_modeling.backend.logic.node_frequency import get_declared_target, set_declared_target
from products.data_modeling.backend.logic.node_suspension import (
    mark_node_suspended,
    query_fingerprint,
    resume_nodes,
    suspension_reset_at,
    suspension_state,
)
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node

ENGINE = "clickhouse"


class TestSuspensionClearedOnQueryChange(BaseTest):
    def _suspended_node(self, *, fingerprint: str | None) -> tuple[DataWarehouseSavedQuery, Node]:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="suspended_model",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node = sync_saved_query_to_dag(saved_query)
        assert node is not None
        mark_node_suspended(node, engine=ENGINE, reason="boom", job_id=str(uuid4()), fingerprint=fingerprint)
        node.save()
        return saved_query, node

    @parameterized.expand(
        [
            ("query_changed", "SELECT 2", True),
            ("query_unchanged", "SELECT 1", False),
        ]
    )
    def test_sync_clears_suspension_only_when_the_query_changed(
        self, _name: str, new_query: str, expect_cleared: bool
    ) -> None:
        saved_query, node = self._suspended_node(fingerprint=query_fingerprint({"query": "SELECT 1"}))

        saved_query.query = {"query": new_query, "kind": "HogQLQuery"}
        saved_query.save()
        sync_saved_query_to_dag(saved_query)

        node.refresh_from_db()
        self.assertEqual(suspension_state(node) == {}, expect_cleared)

    def test_sync_clears_a_suspension_recorded_without_a_fingerprint(self) -> None:
        # Nothing to compare against, so an edit must free them or they stay suspended for good.
        saved_query, node = self._suspended_node(fingerprint=None)

        sync_saved_query_to_dag(saved_query)

        node.refresh_from_db()
        self.assertEqual(suspension_state(node), {})


class TestResumeNodes(BaseTest):
    def test_resume_clears_state_and_records_a_reset_watermark(self) -> None:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="resumed_model",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node = sync_saved_query_to_dag(saved_query)
        assert node is not None
        mark_node_suspended(node, engine=ENGINE, reason="boom", job_id=str(uuid4()), fingerprint=None)
        node.save()

        resumed = resume_nodes([node], by="api")

        self.assertEqual(resumed, 1)
        node.refresh_from_db()
        self.assertEqual(suspension_state(node), {})
        # Without the watermark the next single failure re-suspends it.
        self.assertIsNotNone(suspension_reset_at(node, ENGINE))

    def test_resume_keeps_a_properties_change_committed_after_the_caller_read_the_node(self) -> None:
        # properties is a single JSON blob, so resuming off the caller's in-memory copy would drop
        # whatever a materialization committed to the same row in the meantime.
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="raced_model",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node = sync_saved_query_to_dag(saved_query)
        assert node is not None
        mark_node_suspended(node, engine=ENGINE, reason="boom", job_id=str(uuid4()), fingerprint=None)
        node.save()

        stale = Node.objects.get(id=node.id)
        set_declared_target(Node.objects.get(id=node.id), timedelta(hours=1))

        self.assertEqual(resume_nodes([stale], by="api"), 1)

        node.refresh_from_db()
        self.assertEqual(suspension_state(node), {})
        self.assertEqual(get_declared_target(node), timedelta(hours=1))

    def test_resume_is_a_no_op_on_a_node_that_is_not_suspended(self) -> None:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="healthy_model",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node = sync_saved_query_to_dag(saved_query)
        assert node is not None

        self.assertEqual(resume_nodes([node], by="api"), 0)
        node.refresh_from_db()
        self.assertIsNone(suspension_reset_at(node, ENGINE))
