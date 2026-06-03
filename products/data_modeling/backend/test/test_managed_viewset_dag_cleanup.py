import pytest
from posthog.test.base import BaseTest
from unittest import mock

from products.data_modeling.backend.models import DAG, Node, NodeType
from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind

MODEL_PATH = "products.data_modeling.backend.models.datawarehouse_managed_viewset"


@pytest.mark.django_db
class TestRevenueAnalyticsDagCleanup(BaseTest):
    def test_delete_with_views_deletes_revenue_analytics_dag_and_schedule(self):
        mv = DataWarehouseManagedViewSet.objects.create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        )
        ra_dag = DAG.get_or_create_revenue_analytics(self.team)
        Node.objects.create(team=self.team, dag=ra_dag, name="some_table", type=NodeType.TABLE)

        with (
            mock.patch(f"{MODEL_PATH}._delete_dag_schedule_best_effort") as mock_delete_schedule,
            self.captureOnCommitCallbacks(execute=True),
        ):
            mv.delete_with_views()

        assert not DAG.objects.filter(id=ra_dag.id).exists()
        assert not Node.objects.filter(dag_id=ra_dag.id).exists()
        mock_delete_schedule.assert_called_once_with(str(ra_dag.id), self.team.id)

    def test_delete_with_views_is_noop_when_no_revenue_analytics_dag(self):
        mv = DataWarehouseManagedViewSet.objects.create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        )

        with mock.patch(f"{MODEL_PATH}._delete_dag_schedule_best_effort") as mock_delete_schedule:
            mv.delete_with_views()

        mock_delete_schedule.assert_not_called()
        assert not DataWarehouseManagedViewSet.objects.filter(id=mv.id).exists()
