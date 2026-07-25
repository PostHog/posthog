from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import override_settings
from django.urls import reverse

from products.data_modeling.backend.facade.models import (
    DAG,
    DataModelingJob,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Node,
    NodeType,
)


@override_settings(TEMPORAL_UI_HOST="https://temporal.example.com", TEMPORAL_NAMESPACE="prod")
class TestDataModelingDAGAdminTiers(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True  # is_superuser is a read-only alias for is_staff
        self.user.save()
        self.client.force_login(self.user)
        self.dag = DAG.objects.create(team=self.team, name="Default")

    def _node(self, name: str, target_seconds: int | None) -> Node:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=name, team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        properties = {"system": {"frequency": {"target_seconds": target_seconds}}} if target_seconds else {}
        return Node.objects.create(
            team=self.team, dag=self.dag, saved_query=saved_query, type=NodeType.MAT_VIEW, properties=properties
        )

    def test_tiers_page_renders_each_tier_with_temporal_links(self):
        node = self._node("daily_model", int(timedelta(days=1).total_seconds()))
        parent_workflow_id = f"execute-dag-{self.dag.id}:86400-2026-07-25T03:00:00Z"
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=node.saved_query,
            status=DataModelingJobStatus.COMPLETED,
            parent_workflow_id=parent_workflow_id,
            workflow_id="materialize-view-child",
            workflow_run_id="run-1",
        )

        response = self.client.get(reverse("admin:data_modeling_dag_tiers", args=[self.dag.id]))
        content = response.content.decode()

        assert response.status_code == 200
        assert "daily_model" in content
        assert "1day" in content
        assert f"https://temporal.example.com/namespaces/prod/schedules/execute-dag-{self.dag.id}:86400" in content
        assert "https://temporal.example.com/namespaces/prod/workflows/materialize-view-child/run-1" in content

    def test_tiers_page_renders_for_a_dag_with_no_targets(self):
        self._node("untargeted_model", None)

        response = self.client.get(reverse("admin:data_modeling_dag_tiers", args=[self.dag.id]))
        content = response.content.decode()

        assert response.status_code == 200
        assert "has no tiers" in content
        assert "untargeted_model" in content

    def test_tiers_page_requires_staff(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(reverse("admin:data_modeling_dag_tiers", args=[self.dag.id]))

        assert response.status_code == 302
        assert "/admin/login/" in response.url
