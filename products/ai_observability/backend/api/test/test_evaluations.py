from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import IntegrityError, transaction

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
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_can_create_evaluation_config(self):
        # Creating enabled+keyless only validates for a grandfathered team; pin the cutoff for determinism.
        with self.settings(AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE="2999-12-31T00:00:00+00:00"):
            EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=50)
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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Evaluation.objects.count(), 1)

        evaluation_config = Evaluation.objects.first()
        assert evaluation_config is not None
        self.assertEqual(evaluation_config.name, "Test Evaluation")
        self.assertEqual(evaluation_config.description, "Test Description")
        self.assertEqual(evaluation_config.enabled, True)
        self.assertEqual(evaluation_config.evaluation_type, "llm_judge")
        self.assertEqual(evaluation_config.evaluation_config, {"prompt": "Test prompt"})
        self.assertEqual(evaluation_config.output_type, "boolean")
        self.assertEqual(evaluation_config.output_config, {"allows_na": False})
        self.assertEqual(len(evaluation_config.conditions), 1)
        self.assertEqual(evaluation_config.conditions[0]["id"], "test-condition")
        self.assertEqual(evaluation_config.team, self.team)
        self.assertEqual(evaluation_config.created_by, self.user)
        self.assertEqual(evaluation_config.deleted, False)

        # The viewset auto-creates a default EvaluationReport so reports are generated
        # from the start, even before the user configures delivery targets.
        reports = EvaluationReport.objects.filter(evaluation=evaluation_config)
        self.assertEqual(reports.count(), 1)
        report = reports.first()
        assert report is not None
        self.assertEqual(report.frequency, "every_n")
        self.assertEqual(report.trigger_threshold, 100)
        self.assertTrue(report.enabled)
        self.assertFalse(report.deleted)
        self.assertEqual(report.delivery_targets, [])

    def test_target_defaults_to_generation(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Default target",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["target"], "generation")

    def test_can_create_trace_target_evaluation(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Trace target",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
                "target": "trace",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["target"], "trace")
        evaluation = Evaluation.objects.get(name="Trace target")
        self.assertEqual(evaluation.target, "trace")
        self.assertEqual(evaluation.target_config, {"window_seconds": 30 * 60})
        # Reports run a generation-oriented agent — a trace eval must not get an auto-created report.
        self.assertEqual(EvaluationReport.objects.filter(evaluation=evaluation).count(), 0)

    def test_trace_target_accepts_custom_window(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Trace custom window",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
                "target": "trace",
                "target_config": {"window_seconds": 120},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["target_config"], {"window_seconds": 120})

    def test_rejects_window_below_minimum(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Trace tiny window",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
                "target": "trace",
                "target_config": {"window_seconds": 5},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "target_config")

    def test_generation_target_strips_window_config(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Generation with stray config",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
                "target": "generation",
                "target_config": {"window_seconds": 120},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["target_config"], {})

    def test_rejects_unknown_window_config_key(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Trace unknown key",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
                "target": "trace",
                "target_config": {"window_seconds": 120, "unexpected": True},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "target_config")

    def test_rejects_invalid_target(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Bad target",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "Test prompt"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
                "target": "session",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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
                    "evaluation_type": "llm_judge",
                    "evaluation_config": {"prompt": "Test prompt"},
                    "output_type": "boolean",
                    "output_config": {},
                    "conditions": [],
                },
            )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(Evaluation.objects.filter(name="Will Rollback").count(), 0)
        self.assertEqual(EvaluationReport.objects.count(), 0)

    def test_can_create_sentiment_evaluation_without_default_report(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Sentiment Evaluation",
                "enabled": True,
                "evaluation_type": "sentiment",
                "evaluation_config": {},
                "output_type": "sentiment",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        evaluation = Evaluation.objects.get(id=response.data["id"])
        self.assertEqual(evaluation.evaluation_type, "sentiment")
        self.assertEqual(evaluation.evaluation_config, {"source": "user_messages"})
        self.assertEqual(evaluation.output_type, "sentiment")
        self.assertEqual(evaluation.output_config, {})
        self.assertEqual(EvaluationReport.objects.filter(evaluation=evaluation).count(), 0)

    def test_rejects_sentiment_evaluation_with_trace_target(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Sentiment over a trace",
                "evaluation_type": "sentiment",
                "evaluation_config": {},
                "output_type": "sentiment",
                "output_config": {},
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
                "target": "trace",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "target")
        self.assertEqual(Evaluation.objects.count(), 0)

    def test_sentiment_evaluation_rejects_model_configuration(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Sentiment Evaluation",
                "enabled": True,
                "evaluation_type": "sentiment",
                "evaluation_config": {},
                "output_type": "sentiment",
                "output_config": {},
                "model_configuration": {
                    "provider": "openai",
                    "model": "gpt-5-mini",
                    "provider_key_id": None,
                },
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "model_configuration")

    def test_clearing_model_configuration_with_explicit_null(self):
        mc = LLMModelConfiguration.objects.create(team=self.team, provider="openai", model="gpt-5-mini")
        eval_obj = Evaluation.objects.create(
            team=self.team,
            name="Judge",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test"},
            output_type="boolean",
            model_configuration=mc,
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"name": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertEqual(eval_obj.model_configuration_id, mc.id)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"model_configuration": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertIsNone(eval_obj.model_configuration)
        self.assertFalse(LLMModelConfiguration.objects.filter(id=mc.id).exists())

    def test_db_constraint_blocks_model_config_on_non_judge_eval(self):
        # QuerySet.update() bypasses Evaluation.save(), so this exercises the DB constraint itself.
        mc = LLMModelConfiguration.objects.create(team=self.team, provider="openai", model="gpt-5-mini")
        hog_eval = Evaluation.objects.create(
            team=self.team,
            name="Hog",
            evaluation_type="hog",
            output_type="boolean",
            model_configuration=None,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Evaluation.objects.filter(id=hog_eval.id).update(model_configuration=mc)

    @parameterized.expand(
        [
            ("sentiment_boolean", "sentiment", "boolean", {}, {}),
            ("llm_judge_sentiment", "llm_judge", "sentiment", {"prompt": "Test prompt"}, {}),
        ]
    )
    def test_rejects_unsupported_evaluation_output_type_combinations(
        self, _name, evaluation_type, output_type, evaluation_config, output_config
    ):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Unsupported Evaluation",
                "enabled": True,
                "evaluation_type": evaluation_type,
                "evaluation_config": evaluation_config,
                "output_type": output_type,
                "output_config": output_config,
                "conditions": [{"id": "test-condition", "rollout_percentage": 50, "properties": []}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "config")
        self.assertEqual(Evaluation.objects.count(), 0)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

        evaluation_names = [evaluation["name"] for evaluation in response.data["results"]]
        self.assertIn("Evaluation 1", evaluation_names)
        self.assertIn("Evaluation 2", evaluation_names)

        # Default (non-MCP) list keeps the full payload the web UI relies on.
        first = next(e for e in response.data["results"] if e["name"] == "Evaluation 1")
        self.assertIn("evaluation_config", first)
        self.assertIn("conditions", first)
        self.assertIn("output_config", first)
        self.assertIn("model_configuration", first)
        self.assertEqual(first["evaluation_config"], {"prompt": "Prompt 1"})

    def test_can_filter_evaluations_by_evaluation_type(self):
        Evaluation.objects.create(
            name="Judge evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Prompt"},
            output_type="boolean",
            output_config={},
            team=self.team,
            created_by=self.user,
        )
        Evaluation.objects.create(
            name="Sentiment evaluation",
            evaluation_type="sentiment",
            evaluation_config={"source": "user_messages"},
            output_type="sentiment",
            output_config={},
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?evaluation_type=sentiment")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([evaluation["name"] for evaluation in response.data["results"]], ["Sentiment evaluation"])

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        first = response.data["results"][0]
        for dropped in (
            "evaluation_config",
            "output_config",
            "conditions",
            "model_configuration",
            "created_by",
            "deleted",
        ):
            self.assertNotIn(dropped, first)
        self.assertIn("name", first)
        self.assertIn("evaluation_type", first)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Test Evaluation")
        self.assertEqual(response.data["description"], "Test Description")
        self.assertEqual(response.data["enabled"], True)
        self.assertEqual(response.data["evaluation_type"], "llm_judge")
        self.assertEqual(response.data["evaluation_config"], {"prompt": "Test prompt"})

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        evaluation_config.refresh_from_db()
        self.assertEqual(evaluation_config.name, "Updated Name")
        self.assertEqual(evaluation_config.description, "Updated Description")
        self.assertEqual(evaluation_config.enabled, False)
        self.assertEqual(evaluation_config.evaluation_config, {"prompt": "Updated prompt"})

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
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Accuracy Evaluation")

        # Search by description
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?search=performance")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Performance Evaluation")

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Enabled Evaluation")

        # Filter for disabled only
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/?enabled=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Disabled Evaluation")

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
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # List should not include other team's evaluation configs
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "name")

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "evaluation_type")

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "config")

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "evaluation_config")
        self.assertEqual(Evaluation.objects.count(), 0)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

        # Should not be accessible for retrieval
        response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{evaluation_config.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["conditions"]), 2)
        self.assertEqual(response.data["conditions"][0]["rollout_percentage"], 50)
        self.assertEqual(len(response.data["conditions"][0]["properties"]), 1)
        self.assertEqual(response.data["conditions"][0]["properties"][0]["key"], "$ai_model_name")

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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        condition = response.data["conditions"][0]
        self.assertNotIn("sampling_rate", condition)
        self.assertEqual(condition["rollout_percentage"], 100)

        stored = Evaluation.objects.get(id=response.data["id"])
        self.assertEqual(stored.conditions[0]["rollout_percentage"], 100)
        self.assertNotIn("sampling_rate", stored.conditions[0])

        get_response = self.client.get(f"/api/environments/{self.team.id}/evaluations/{response.data['id']}/")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertNotIn("sampling_rate", get_response.data["conditions"][0])
        self.assertEqual(get_response.data["conditions"][0]["rollout_percentage"], 100)

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.data["conditions"][0]["rollout_percentage"], rollout_percentage)


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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIn("event_uuid", r)
            self.assertIn("result", r)
            self.assertIn("reasoning", r)
            self.assertIn("error", r)
            self.assertTrue(r["result"])
            self.assertIsNone(r["error"])

    def test_test_hog_compilation_error(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": "this is not valid hog {{{{"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Compilation error", response.json()["error"])

    def test_test_hog_empty_source_rejected(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": ""},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("posthog.hogql.query.execute_hogql_query")
    def test_test_hog_no_events(self, mock_query):
        mock_query.return_value = self._mock_hogql_response(0)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": "return true"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])
        self.assertIn("message", response.json())

    @patch("posthog.hogql.query.execute_hogql_query")
    def test_test_hog_handles_runtime_error(self, mock_query):
        mock_query.return_value = self._mock_hogql_response(1)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": "return 42"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["result"])
        self.assertIn("Must return boolean", results[0]["error"])

    @patch("posthog.hogql.query.execute_hogql_query")
    def test_test_hog_uses_null_safe_comparisons(self, mock_query):
        mock_query.return_value = self._mock_hogql_response(1)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/test_hog/",
            {"source": "return properties.missing <= 1.0"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["result"])
        self.assertIsNone(results[0]["error"])


class TestEnableBlockingWhenKeyRequired(APIBaseTest):
    """Enabling a keyless llm_judge eval must mirror the runtime funded-inference gate: a config
    with no pinned key falls back to the team's active key for the same provider, else only
    grandfathered (mid-trial, pre-cutoff) teams may run it via funded inference. Anything the
    serializer lets through here would just flap back to disabled on the next Temporal run."""

    def _create_keyless_eval(self, model_configuration=...):
        if model_configuration is ...:
            model_configuration = LLMModelConfiguration.objects.create(
                team=self.team, provider="openai", model="gpt-5-mini"
            )
        return Evaluation.objects.create(
            team=self.team,
            name="Keyless Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test"},
            output_type="boolean",
            model_configuration=model_configuration,
            enabled=False,
        )

    def _create_active_key(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Active Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        return key

    def _enable(self, eval_obj):
        return self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )

    @parameterized.expand(
        [
            ("trial_exhausted_explicit_config", 100, True),
            ("trial_never_started_explicit_config", 0, True),
            ("trial_never_started_null_config", 0, False),
        ]
    )
    def test_blocks_enabling_keyless_eval_when_not_grandfathered(self, _name, trial_evals_used, explicit_config):
        EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=trial_evals_used)
        eval_obj = (
            self._create_keyless_eval() if explicit_config else self._create_keyless_eval(model_configuration=None)
        )

        response = self._enable(eval_obj)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Add a provider API key", str(response.data))
        eval_obj.refresh_from_db()
        self.assertFalse(eval_obj.enabled)

    def test_allows_enabling_keyless_eval_while_grandfathered(self):
        with self.settings(AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE="2999-12-31T00:00:00+00:00"):
            EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=50)
            eval_obj = self._create_keyless_eval()

            response = self._enable(eval_obj)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)

    def test_active_team_key_enables_explicit_keyless_eval(self):
        # An explicit config with no pinned key falls back to the team's active key for the same
        # provider, so it enables even with the trial exhausted (mirrors runtime resolution).
        key = self._create_active_key()
        EvaluationConfig.objects.create(
            team=self.team, trial_eval_limit=100, trial_evals_used=100, active_provider_key=key
        )
        eval_obj = self._create_keyless_eval()

        response = self._enable(eval_obj)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)

    def test_active_team_key_enables_null_config_eval(self):
        # Null configs resolve via the active key at runtime — the gate must not over-block them.
        key = self._create_active_key()
        EvaluationConfig.objects.create(
            team=self.team, trial_eval_limit=100, trial_evals_used=100, active_provider_key=key
        )
        eval_obj = self._create_keyless_eval(model_configuration=None)

        response = self._enable(eval_obj)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)

    def test_unhealthy_active_key_blocks_null_config_eval_even_while_grandfathered(self):
        # Runtime never falls back to funded inference when an active key exists, even unhealthy.
        key = self._create_active_key()
        key.state = LLMProviderKey.State.INVALID
        key.save()
        with self.settings(AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE="2999-12-31T00:00:00+00:00"):
            EvaluationConfig.objects.create(
                team=self.team, trial_eval_limit=100, trial_evals_used=50, active_provider_key=key
            )
            eval_obj = self._create_keyless_eval(model_configuration=None)

            response = self._enable(eval_obj)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("working provider API key", str(response.data))
        eval_obj.refresh_from_db()
        self.assertFalse(eval_obj.enabled)

    def test_detaching_model_configuration_enables_via_active_key(self):
        # The gate must validate the post-detach state, not the stored config.
        key = self._create_active_key()
        EvaluationConfig.objects.create(
            team=self.team, trial_eval_limit=100, trial_evals_used=100, active_provider_key=key
        )
        eval_obj = self._create_keyless_eval()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True, "model_configuration": None},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)
        self.assertIsNone(eval_obj.model_configuration)

    def test_blocks_creating_enabled_keyless_eval_when_not_grandfathered(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Doomed Eval",
                "enabled": True,
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "test"},
                "output_type": "boolean",
                "output_config": {},
                "conditions": [{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Add a provider API key", str(response.data))
        self.assertEqual(Evaluation.objects.filter(name="Doomed Eval").count(), 0)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)

    def test_rejects_enabling_trial_eval_with_unusable_byok_key_when_limit_reached(self):
        EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=100)
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key",
            state=LLMProviderKey.State.INVALID,
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
            name="Invalid BYOK Eval",
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

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("working provider API key", str(response.data))
        eval_obj.refresh_from_db()
        self.assertFalse(eval_obj.enabled)


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
        # Only a grandfathered team gets past the funded gate to the model-allowlist message.
        with self.settings(AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE="2999-12-31T00:00:00+00:00"):
            EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=50)
            eval_obj = self._create_errored_eval(status_reason="model_not_allowed", model="gpt-9")

            response = self.client.patch(
                f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
                {"enabled": True},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not available on the trial plan", str(response.data))

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)
        self.assertEqual(eval_obj.status, "active")
        self.assertIsNone(eval_obj.status_reason)

    def test_rejects_re_enable_when_model_not_allowed_with_unusable_byok_key(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key",
            state=LLMProviderKey.State.INVALID,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        eval_obj = self._create_errored_eval(status_reason="model_not_allowed", model="gpt-9", provider_key=key)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("working provider API key", str(response.data))
        eval_obj.refresh_from_db()
        self.assertFalse(eval_obj.enabled)

    def test_rejects_re_enable_when_provider_key_required_and_no_key(self):
        eval_obj = self._create_errored_eval(status_reason="provider_key_required")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("provider API key", str(response.data))
        eval_obj.refresh_from_db()
        self.assertFalse(eval_obj.enabled)

    def test_allows_re_enable_when_provider_key_required_and_byok_key_attached(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        eval_obj = self._create_errored_eval(status_reason="provider_key_required", provider_key=key)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)
        self.assertIsNone(eval_obj.status_reason)

    @parameterized.expand(
        [
            ("provider_key_deleted",),
            ("provider_key_invalid",),
            ("provider_key_permission_denied",),
            ("provider_key_quota_exceeded",),
            ("provider_key_rate_limited",),
        ]
    )
    def test_rejects_re_enable_when_provider_key_still_missing(self, status_reason):
        eval_obj = self._create_errored_eval(status_reason=status_reason)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("provider API key", str(response.data))

    @parameterized.expand(
        [
            ("provider_key_invalid", LLMProviderKey.State.INVALID),
            ("provider_key_permission_denied", LLMProviderKey.State.ERROR),
            ("provider_key_quota_exceeded", LLMProviderKey.State.ERROR),
            ("provider_key_rate_limited", LLMProviderKey.State.ERROR),
        ]
    )
    def test_rejects_re_enable_when_provider_key_is_still_not_usable(self, status_reason, key_state):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key",
            state=key_state,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        eval_obj = self._create_errored_eval(status_reason=status_reason, provider_key=key)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
            {"enabled": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("working provider API key", str(response.data))

    def test_allows_re_enable_when_model_not_found_with_existing_model_config(self):
        # Grandfather the team so the funded gate passes — this test is about the model_not_found rule.
        with self.settings(AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE="2999-12-31T00:00:00+00:00"):
            EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=50)
            eval_obj = self._create_errored_eval(status_reason="model_not_found")

            response = self.client.patch(
                f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
                {"enabled": True},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)
        self.assertIsNone(eval_obj.status_reason)

    def test_allows_re_enable_when_model_not_found_with_new_model(self):
        with self.settings(AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE="2999-12-31T00:00:00+00:00"):
            EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=50)
            eval_obj = self._create_errored_eval(status_reason="model_not_found", model="missing-model")

            response = self.client.patch(
                f"/api/environments/{self.team.id}/evaluations/{eval_obj.id}/",
                {
                    "enabled": True,
                    "model_configuration": {
                        "provider": "openai",
                        "model": "gpt-5-mini",
                        "provider_key_id": None,
                    },
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)
        self.assertIsNone(eval_obj.status_reason)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        eval_obj.refresh_from_db()
        self.assertTrue(eval_obj.enabled)
        self.assertIsNone(eval_obj.status_reason)
