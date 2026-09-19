from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.ai_observability.backend.api.clustering import ClusteringRunRequestSerializer


class TestClusteringRunRequestSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("cap_below_floor", 0.4, 0.2, False),
            ("cap_equal_to_floor", 0.4, 0.4, True),
            ("cap_above_floor", 0.02, 0.5, True),
        ]
    )
    def test_max_cluster_size_fraction_must_not_undercut_min(
        self, _name: str, min_fraction: float, max_fraction: float, expected_valid: bool
    ) -> None:
        serializer = ClusteringRunRequestSerializer(
            data={
                "clustering_method": "hdbscan",
                "min_cluster_size_fraction": min_fraction,
                "max_cluster_size_fraction": max_fraction,
            }
        )

        assert serializer.is_valid() == expected_valid
        if not expected_valid:
            assert "max_cluster_size_fraction" in serializer.errors


class TestClusteringRunViewSet(APIBaseTest):
    @patch("products.ai_observability.backend.api.clustering.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.ai_observability.backend.api.clustering.sync_connect")
    def test_max_cluster_size_fraction_reaches_the_workflow(
        self, mock_sync_connect: MagicMock, _mock_feature_enabled: MagicMock
    ) -> None:
        mock_sync_connect.return_value = MagicMock(start_workflow=AsyncMock())

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_runs/",
            {"clustering_method": "hdbscan", "max_cluster_size_fraction": 0.3},
            format="json",
        )

        assert response.status_code == status.HTTP_202_ACCEPTED, response.data
        assert response.data["parameters"]["clustering_method_params"]["max_cluster_size_fraction"] == 0.3
        workflow_inputs = mock_sync_connect.return_value.start_workflow.call_args.args[1]
        assert workflow_inputs.clustering_method_params["max_cluster_size_fraction"] == 0.3
