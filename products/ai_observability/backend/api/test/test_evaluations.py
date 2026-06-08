from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Project, Team, User

from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluation_reports import EvaluationReport
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.model_configuration import LLMModelConfiguration
from products.ai_observability.backend.models.provider_keys import LLMProviderKey


def _setup_team():
    org = Organization.objects.create(name="test")
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
    team = Team.objects.create(
        id=project.id,
        project=project,
        organization=org,
        api_token=str(uuid4()),
        test_account_filters=[
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ],
        has_completed_onboarding_for={"product_analytics": True},
    )
    User.objects.create_and_join(org, "test-evaluations@posthog.com", "testpassword123")
    return team


class TestEvaluationConfigsApi(APIBaseTest):
    def test_unauthenticated_user_cannot_access_evaluation_configs(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_can_create_evaluation_config(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test Evaluation",
                "description": "Test Description",
                "enabled": True,
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert Evaluation.objects.count() == 1

        evaluation_config = Evaluation.objects.first()
        assert evaluation_config is not None
        assert evaluation_config.name == "Test Evaluation"
        assert evaluation_config.description == "Test Description"
        assert evaluation_config.enabled
        assert evaluation_config.evaluation_type == "llm_judge"
        assert evaluation_config.evaluation_config == {"prompt": "Test prompt"}
        assert evaluation_config.output_type == "boolean"
        assert evaluation_config.output_config == {"allows_na": False}
        assert len(evaluation_config.conditions) == 1
        assert evaluation_config.conditions[0]["id"] == "test-condition"
        assert evaluation_config.team == self.team
        assert evaluation_config.created_by == self.user
        assert not evaluation_config.deleted

        # The viewset auto-creates a default EvaluationReport so reports are generated
        # from the start, even before the user configures delivery targets.
        reports = EvaluationReport.objects.filter(evaluation=evaluation_config)
        assert reports.count() == 1
        report = reports.first()
        assert report is not None
        assert report.frequency == "every_n"
        assert report.trigger_threshold == 100
        assert report.enabled
        assert not report.deleted
        assert report.delivery_targets == []

    def test_evaluation_rollback_when_auto_report_fails(self):
        """
        perform_create wraps the Evaluation save and the EvaluationReport auto-create in
        transaction.atomic(). If the report insert raises, the evaluation must not persist.
        """
        with patch(
            "products.ai_observability.backend.api.evaluations.EvaluationReport.objects.create",
            side_effect=RuntimeError("boom"),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/evaluations/",
                {
                    "name": "Will Rollback",
                    "enabled": True,
                    "evaluation_type": "llm_judge",
                    "evaluation_config": {"prompt": "Test prompt"},
                    "output_type": "boolean",
                    "output_config": {},
                    "conditions": [],
                },
            )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert Evaluation.objects.filter(name="Will Rollback").count() == 0
        assert EvaluationReport.objects.count() == 0

    def test_can_retrieve_list_of_evaluation_configs(self):
        Evaluation.objects.create(
            name="Evaluation 1",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Prompt 1"},
            output_type="boolean",
            output_config={},
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
            team=self.team,
            created_by=self.user,
        )
        Evaluation.objects.create(
            name="Evaluation 2",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Prompt 2"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2

        evaluation_names = [evaluation["name"] for evaluation in response.data["results"]]
        assert "Evaluation 1" in evaluation_names
        assert "Evaluation 2" in evaluation_names

        # Default (non-MCP) list keeps the full payload the web UI relies on.
        first = next(e for e in response.data["results"] if e["name"] == "Evaluation 1")
        assert "evaluation_config" in first
        assert "conditions" in first
        assert "output_config" in first
        assert "model_configuration" in first
        assert first["evaluation_config"] == {"prompt": "Prompt 1"}

    def test_mcp_list_returns_slim_payload(self):
        Evaluation.objects.create(
            name="Evaluation 1",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Prompt 1"},
            output_type="boolean",
            output_config={},
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/evaluations/",
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        first = response.data["results"][0]
        for dropped in (
            "evaluation_config",
            "output_config",
            "conditions",
            "model_configuration",
            "created_by",
            "deleted",
        ):
            assert dropped not in first
        assert "name" in first
        assert "evaluation_type" in first

    def test_can_get_single_evaluation_config(self):
        evaluation_config = Evaluation.objects.create(
            name="Test Evaluation",
            description="Test Description",
            enabled=True,
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            conditions=[{"id": "test", "rollout_percentage": 100, "properties": []}],
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Test Evaluation"
        assert response.data["description"] == "Test Description"
        assert response.data["enabled"]
        assert response.data["evaluation_type"] == "llm_judge"
        assert response.data["evaluation_config"] == {"prompt": "Test prompt"}

    def test_can_edit_evaluation_config(self):
        evaluation_config = Evaluation.objects.create(
            name="Original Name",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Original prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/",
            {
                "name": "Updated Name",
                "description": "Updated Description",
                "enabled": False,
                "evaluation_config": {"prompt": "Updated prompt"},
            },
        )
        assert response.status_code == status.HTTP_200_OK

        evaluation_config.refresh_from_db()
        assert evaluation_config.name == "Updated Name"
        assert evaluation_config.description == "Updated Description"
        assert not evaluation_config.enabled
        assert evaluation_config.evaluation_config == {"prompt": "Updated prompt"}

    def test_delete_method_returns_405(self):
        evaluation_config = Evaluation.objects.create(
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_can_search_evaluation_configs(self):
        Evaluation.objects.create(
            name="Accuracy Evaluation",
            description="Tests accuracy",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )
        Evaluation.objects.create(
            name="Performance Evaluation",
            description="Tests performance",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )

        # Search by name
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?search=accuracy")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Accuracy Evaluation"

        # Search by description
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?search=performance")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Performance Evaluation"

    def test_can_filter_by_enabled_status(self):
        Evaluation.objects.create(
            name="Enabled Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            team=self.team,
            created_by=self.user,
        )
        Evaluation.objects.create(
            name="Disabled Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=False,
            team=self.team,
            created_by=self.user,
        )

        # Filter for enabled only
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?enabled=true")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Enabled Evaluation"

        # Filter for disabled only
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?enabled=false")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Disabled Evaluation"

    def test_cannot_access_other_teams_evaluation_configs(self):
        other_team = _setup_team()

        # Create evaluation config for other team
        other_evaluation = Evaluation.objects.create(
            name="Other Team Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=other_team,
            created_by=self.user,
        )

        # Try to access other team's evaluation config
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{other_evaluation.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # List should not include other team's evaluation configs
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    def test_validation_requires_required_fields(self):
        # Missing name
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["attr"] == "name"

        # Missing evaluation_type
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test Evaluation",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["attr"] == "evaluation_type"

        # Empty evaluation_config should fail validation
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test Evaluation",
                "evaluation_type": "llm_judge",
                "evaluation_config": {},
                "output_type": "boolean",
                "output_config": {},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["attr"] == "config"

    def test_invalid_hog_source_returns_400_not_500(self):
        # Malformed Hog source passes serializer config validation (non-empty source) but fails
        # to compile in the model's save(). The compile failure must surface as a 400 validation
        # error, not an unhandled 500 — `|` is the exact character that triggered this in production.
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Bad Hog Eval",
                "evaluation_type": "hog",
                "evaluation_config": {"source": "return |"},
                "output_type": "boolean",
                "output_config": {},
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["attr"] == "evaluation_config"
        assert Evaluation.objects.count() == 0

    def test_deleted_evaluation_configs_not_returned(self):
        evaluation_config = Evaluation.objects.create(
            name="Deleted Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
            deleted=True,
        )

        # Should not appear in list
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

        # Should not be accessible for retrieval
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_conditions_with_property_filters(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Test with Properties",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Evaluate this"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [
                    {
                        "id": "cond-1",
                        "rollout_percentage": 50,
                        "properties": [
                            {"key": "$ai_model_name", "value": "gpt-4", "operator": "exact", "type": "event"}
                        ],
                    },
                    {
                        "id": "cond-2",
                        "rollout_percentage": 100,
                        "properties": [
                            {"key": "custom_property", "value": "test_value", "operator": "exact", "type": "event"}
                        ],
                    },
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["conditions"]) == 2
        assert response.data["conditions"][0]["rollout_percentage"] == 50
        assert len(response.data["conditions"][0]["properties"]) == 1
        assert response.data["conditions"][0]["properties"][0]["key"] == "$ai_model_name"

    def test_unknown_condition_keys_are_dropped_and_rollout_percentage_defaults_to_100(self):
        # Regression: callers (notably MCP) previously sent `sampling_rate` instead of
        # `rollout_percentage` and the unstructured JSONField silently persisted it. The
        # dispatcher reads `rollout_percentage`, so the eval looked configured on the
        # API surface (GET echoed `sampling_rate`) but never fired.
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Typo eval",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Evaluate"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "cond-1", "sampling_rate": 100, "properties": []}],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        condition = response.data["conditions"][0]
        assert "sampling_rate" not in condition
        assert condition["rollout_percentage"] == 100

        stored = Evaluation.objects.get(id=response.data["id"])
        assert stored.conditions[0]["rollout_percentage"] == 100
        assert "sampling_rate" not in stored.conditions[0]

        get_response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{response.data['id']}/")
        assert get_response.status_code == status.HTTP_200_OK
        assert "sampling_rate" not in get_response.data["conditions"][0]
        assert get_response.data["conditions"][0]["rollout_percentage"] == 100

    @parameterized.expand([(-1,), (101,), (150,)])
    def test_rollout_percentage_out_of_range_rejected(self, rollout_percentage):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Out of range",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Evaluate"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "cond-1", "rollout_percentage": rollout_percentage, "properties": []}],
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand([(0,), (100,)])
    def test_rollout_percentage_boundaries_accepted(self, rollout_percentage):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Boundary",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Evaluate"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "cond-1", "rollout_percentage": rollout_percentage, "properties": []}],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.data["conditions"][0]["rollout_percentage"] == rollout_percentage


class TestTestHogEndpoint(APIBaseTest):
    def _mock_hogql_response(self, count=1):
        from posthog.hogql.query import HogQLQueryResponse

        rows = [
            (
                str(uuid4()),
                "$ai_generation",
                {"$ai_input": "What is 2+2?", "$ai_output": "4"},
                "user-1",
            )
            for _ in range(count)
        ]
        return HogQLQueryResponse(results=rows, columns=["uuid", "event", "properties", "distinct_id"])

    @patch("posthog.hogql.query.execute_hogql_query")
    def test_test_hog_compiles_and_executes(self, mock_query):
        mock_query.return_value = self._mock_hogql_response(2)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": "return length(output) > 0", "sample_count": 2},
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        for r in results:
            assert "event_uuid" in r
            assert "result" in r
            assert "reasoning" in r
            assert "error" in r
            assert r["result"]
            assert r["error"] is None

    def test_test_hog_compilation_error(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": "this is not valid hog {{{{"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Compilation error" in response.json()["error"]

    def test_test_hog_empty_source_rejected(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": ""},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.hogql.query.execute_hogql_query")
    def test_test_hog_no_events(self, mock_query):
        mock_query.return_value = self._mock_hogql_response(0)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": "return true"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []
        assert "message" in response.json()

    @patch("posthog.hogql.query.execute_hogql_query")
    def test_test_hog_handles_runtime_error(self, mock_query):
        mock_query.return_value = self._mock_hogql_response(1)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": "return 42"},
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["result"] is None
        assert "Must return boolean" in results[0]["error"]


class TestEnableBlockingWhenTrialExhausted(APIBaseTest):
    def _create_trial_eval(self, enabled=False):
        mc = LLMModelConfiguration.objects.create(team=self.team, provider="openai", model="gpt-5-mini")
        return Evaluation.objects.create(
            team=self.team,
            name="Trial Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test"},
            output_type="boolean",
            model_configuration=mc,
            enabled=enabled,
        )

    def test_blocks_enabling_trial_eval_when_limit_reached(self):
        EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=100)
        eval_obj = self._create_trial_eval(enabled=False)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Trial evaluation limit reached" in str(response.data)

    def test_allows_enabling_trial_eval_when_limit_not_reached(self):
        EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=50)
        eval_obj = self._create_trial_eval(enabled=False)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        eval_obj.refresh_from_db()
        assert eval_obj.enabled

    def test_allows_enabling_hog_eval_when_limit_reached(self):
        EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=100)
        eval_obj = Evaluation.objects.create(
            team=self.team,
            name="Hog Eval",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            output_config={},
            enabled=False,
            created_by=self.user,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        eval_obj.refresh_from_db()
        assert eval_obj.enabled

    def test_allows_enabling_byok_eval_when_limit_reached(self):
        EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=100)
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        mc = LLMModelConfiguration.objects.create(
            team=self.team,
            provider="openai",
            model="gpt-5-mini",
            provider_key=key,
        )
        eval_obj = Evaluation.objects.create(
            team=self.team,
            name="BYOK Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test"},
            output_type="boolean",
            model_configuration=mc,
            enabled=False,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        eval_obj.refresh_from_db()
        assert eval_obj.enabled


class TestReEnableValidatesRootCauseResolved(APIBaseTest):
    """When an eval is in the error state, flipping enabled=True must fail unless the condition
    that put it there is resolved — otherwise the next workflow run just re-disables it for the
    same reason. Matters for agent callers who can't see a red banner."""

    def _create_errored_eval(self, status_reason, model="gpt-5-mini", provider_key=None):
        mc = LLMModelConfiguration.objects.create(
            team=self.team, provider="openai", model=model, provider_key=provider_key
        )
        eval_obj = Evaluation.objects.create(
            team=self.team,
            name="Errored",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "?"},
            output_type="boolean",
            model_configuration=mc,
        )
        eval_obj.set_status("error", status_reason)
        eval_obj.refresh_from_db()
        return eval_obj

    def test_rejects_re_enable_when_model_still_not_allowed(self):
        eval_obj = self._create_errored_eval(status_reason="model_not_allowed", model="gpt-9")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not available on the trial plan" in str(response.data)

    def test_allows_re_enable_when_byok_key_attached_even_if_model_not_allowed(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        eval_obj = self._create_errored_eval(status_reason="model_not_allowed", model="gpt-9", provider_key=key)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        eval_obj.refresh_from_db()
        assert eval_obj.enabled
        assert eval_obj.status == "active"
        assert eval_obj.status_reason is None

    def test_rejects_re_enable_when_provider_key_still_missing(self):
        eval_obj = self._create_errored_eval(status_reason="provider_key_deleted")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "provider API key" in str(response.data)

    def test_allows_re_enable_when_provider_key_attached(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        eval_obj = self._create_errored_eval(status_reason="provider_key_deleted", provider_key=key)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        eval_obj.refresh_from_db()
        assert eval_obj.enabled
        assert eval_obj.status_reason is None
