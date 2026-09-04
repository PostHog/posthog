import uuid
from datetime import datetime

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl

from ...api.evaluation_runs import _evaluation_workflow_prefix
from ...models.evaluations import Evaluation


@pytest.mark.parametrize(
    ("evaluation_type", "expected_prefix"),
    [
        ("llm_judge", "llma-llm-eval"),
        ("hog", "llma-hog-eval"),
        ("sentiment", "llma-sentiment-eval"),
    ],
)
def test_evaluation_workflow_prefix_maps_every_supported_runtime(evaluation_type: str, expected_prefix: str):
    assert _evaluation_workflow_prefix(evaluation_type) == expected_prefix


def test_evaluation_workflow_prefix_rejects_unknown_runtime():
    with pytest.raises(ValueError, match="Unsupported evaluation type for workflow prefix: unknown"):
        _evaluation_workflow_prefix("unknown")


class TestEvaluationRunViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Is this response accurate?"},
            output_type="boolean",
            output_config={},
            enabled=True,
        )

    def test_create_requires_access_to_requested_evaluation(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        other_user = User.objects.create_and_join(self.organization, "run-viewer@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=other_user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="evaluation", access_level="editor", organization_member=membership
        )
        AccessControl.objects.create(
            team=self.team,
            resource="evaluation",
            resource_id=str(self.evaluation.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(other_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(self.evaluation.id),
                "target_event_id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
            },
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.ai_observability.backend.api.evaluation_runs.query_with_columns")
    @patch("products.ai_observability.backend.api.evaluation_runs.sync_connect")
    def test_create_evaluation_run_success(self, mock_connect, mock_query):
        """Test successfully creating an evaluation run"""
        # Mock Temporal client
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_connect.return_value = mock_client

        target_event_id = str(uuid.uuid4())
        timestamp = datetime.now()

        # Mock ClickHouse query to return event data
        mock_query.return_value = [
            {
                "uuid": target_event_id.replace("-", ""),
                "event": "$ai_generation",
                "properties": '{"$ai_input": "test input", "$ai_output": "test output"}',
                "timestamp": timestamp,
                "team_id": self.team.id,
                "distinct_id": "test_user",
                "elements_chain": "",
                "created_at": timestamp,
                "person_id": str(uuid.uuid4()),
            }
        ]

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(self.evaluation.id),
                "target_event_id": target_event_id,
                "timestamp": timestamp.isoformat(),
                "event": "$ai_generation",
                "distinct_id": "test_user",
            },
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()

        assert data["status"] == "started"
        assert "workflow_id" in data
        assert data["evaluation"]["id"] == str(self.evaluation.id)
        assert data["target_event_id"] == target_event_id

        # Verify Temporal workflow was started
        mock_client.start_workflow.assert_called_once()
        call_args = mock_client.start_workflow.call_args

        assert call_args[0][0] == "run-evaluation"  # workflow name
        assert call_args[1]["task_queue"] == settings.LLMA_EVALS_TASK_QUEUE

        # Verify the workflow inputs contain event data
        workflow_inputs = call_args[0][1]
        assert workflow_inputs.evaluation_id == str(self.evaluation.id)
        assert workflow_inputs.event_data is not None
        assert workflow_inputs.event_data["uuid"] == target_event_id.replace("-", "")

    @patch("products.ai_observability.backend.api.evaluation_runs.query_with_columns")
    @patch("products.ai_observability.backend.api.evaluation_runs.sync_connect")
    def test_create_evaluation_run_tags_clickhouse_query(self, mock_connect, mock_query):
        """The manual eval-trigger ClickHouse lookup must run inside an LLM analytics tag context.

        Mocking `query_with_columns` bypasses `sync_execute`'s tag plumbing, so assert directly
        that the tags are set on the active context at the moment the query runs.
        """
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_connect.return_value = mock_client

        target_event_id = str(uuid.uuid4())
        timestamp = datetime.now()
        captured: dict = {}

        def capture_tags(*args, **kwargs):
            tags = get_query_tags()
            captured["product"] = tags.product
            captured["feature"] = tags.feature
            captured["team_id"] = tags.team_id
            return [
                {
                    "uuid": target_event_id.replace("-", ""),
                    "event": "$ai_generation",
                    "properties": "{}",
                    "timestamp": timestamp,
                    "team_id": self.team.id,
                    "distinct_id": "test_user",
                    "person_id": str(uuid.uuid4()),
                }
            ]

        mock_query.side_effect = capture_tags

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(self.evaluation.id),
                "target_event_id": target_event_id,
                "timestamp": timestamp.isoformat(),
                "event": "$ai_generation",
                "distinct_id": "test_user",
            },
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert captured["product"] == Product.LLM_ANALYTICS
        assert captured["feature"] == Feature.QUERY
        assert captured["team_id"] == self.team.id

    def test_create_evaluation_run_invalid_evaluation(self):
        """Test creating evaluation run with non-existent evaluation"""
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(uuid.uuid4()),
                "target_event_id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "event": "$ai_generation",
                # distinct_id is optional, testing without it
            },
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(["trace", "session"])
    def test_create_evaluation_run_refuses_aggregate_targets(self, target: str):
        """This endpoint runs one generation through the generation workflow. Accepting an aggregate
        target ran it as a generation and emitted a verdict with $ai_target_type 'generation_uuid'
        under that evaluation's name, which counted towards its pass rate while being invisible on
        the trace or session it belonged to."""
        aggregate_evaluation = Evaluation.objects.create(
            team=self.team,
            name=f"{target} target",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            output_config={},
            target=target,
            enabled=False,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(aggregate_evaluation.id),
                "target_event_id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "event": "$ai_generation",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert target in body["detail"]
        # Callers match on this code, so a rename is a breaking change and should fail here.
        assert body["code"] == "evaluation_target_mismatch"

    def test_create_evaluation_run_missing_params(self):
        """Test creating evaluation run with missing parameters"""
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(self.evaluation.id),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["attr"] == "target_event_id"
        assert body["type"] == "validation_error"

    def test_create_evaluation_run_different_team(self):
        """Test creating evaluation run for evaluation from different team"""
        other_team = self.organization.teams.create(name="Other Team")
        other_evaluation = Evaluation.objects.create(
            team=other_team,
            name="Other Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test"},
            output_type="boolean",
            output_config={},
            enabled=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluation_runs/",
            {
                "evaluation_id": str(other_evaluation.id),
                "target_event_id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "event": "$ai_generation",
                "distinct_id": "test_user",
            },
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
