from typing import Any

from django.test import override_settings

from rest_framework import status

from posthog.test.activity_log_utils import ActivityLogTestHelper

from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.model_configuration import LLMModelConfiguration
from products.ai_observability.backend.models.provider_keys import LLMProviderKey


def _create_evaluation_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "Test Evaluation",
        "description": "Initial",
        "enabled": True,
        "evaluation_type": "llm_judge",
        "model_configuration": {
            "provider": "openai",
            "model": "gpt-5-mini",
            "provider_key_id": None,
        },
        "evaluation_config": {"prompt": "Test prompt"},
        "output_type": "boolean",
        "output_config": {},
        "conditions": [
            {"id": "cond-1", "rollout_percentage": 25, "properties": []},
        ],
    }
    payload.update(overrides)
    return payload


# The create payloads are keyless llm_judge with enabled=True, which only validates for a
# grandfathered team.
@override_settings(AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE="2999-12-31T00:00:00+00:00")
class TestEvaluationActivityLogging(ActivityLogTestHelper):
    def setUp(self) -> None:
        super().setUp()
        EvaluationConfig.objects.create(team=self.team, trial_eval_limit=100, trial_evals_used=50)

    def _create_evaluation(self, **overrides: Any) -> dict[str, Any]:
        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            _create_evaluation_payload(**overrides),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def _update_evaluation(self, evaluation_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{evaluation_id}/",
            updates,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def test_evaluation_model_has_activity_mixin(self):
        from posthog.models.activity_logging.model_activity import ModelActivityMixin

        self.assertTrue(issubclass(Evaluation, ModelActivityMixin))

    def test_evaluation_scope_in_activity_log_types(self):
        from typing import get_args

        from posthog.models.activity_logging.activity_log import ActivityScope

        self.assertIn("Evaluation", get_args(ActivityScope))

    def test_creating_evaluation_logs_created_activity(self):
        evaluation = self._create_evaluation()

        logs = self.get_activity_logs_for_item("Evaluation", evaluation["id"])
        self.assertEqual(len(logs), 1)

        log_entry = logs[0]
        self.assertEqual(log_entry.activity, "created")
        self.assertEqual(log_entry.scope, "Evaluation")
        self.assertEqual(log_entry.item_id, evaluation["id"])
        self.assertEqual(log_entry.detail.get("name"), "Test Evaluation")

    def test_updating_rollout_percentage_logs_conditions_change(self):
        evaluation = self._create_evaluation()
        self.clear_activity_logs()

        self._update_evaluation(
            evaluation["id"],
            {
                "conditions": [
                    {"id": "cond-1", "rollout_percentage": 100, "properties": []},
                ]
            },
        )

        logs = self.get_activity_logs_for_item("Evaluation", evaluation["id"])
        self.assertEqual(len(logs), 1)
        changes = logs[0].detail.get("changes", [])

        conditions_change = next((c for c in changes if c.get("field") == "conditions"), None)
        self.assertIsNotNone(conditions_change, f"Expected conditions change in {changes}")
        assert conditions_change is not None
        self.assertEqual(conditions_change["before"][0]["rollout_percentage"], 25)
        self.assertEqual(conditions_change["after"][0]["rollout_percentage"], 100)

    def test_bytecode_is_stripped_from_conditions_diff(self):
        # Re-saving without semantic changes should produce no `conditions` diff,
        # even though `save()` recompiles bytecode each time.
        evaluation = self._create_evaluation()
        self.clear_activity_logs()

        self._update_evaluation(
            evaluation["id"],
            # Same rollout/properties as the original — bytecode will recompile, but
            # nothing the user can perceive has changed.
            {
                "conditions": [
                    {"id": "cond-1", "rollout_percentage": 25, "properties": []},
                ]
            },
        )

        logs = self.get_activity_logs_for_item("Evaluation", evaluation["id"])
        self.assertEqual(len(logs), 0)

    def test_toggling_enabled_logs_status_and_enabled(self):
        evaluation = self._create_evaluation()
        self.clear_activity_logs()

        self._update_evaluation(evaluation["id"], {"enabled": False})

        logs = self.get_activity_logs_for_item("Evaluation", evaluation["id"])
        self.assertEqual(len(logs), 1)
        changes = logs[0].detail.get("changes", [])
        field_names = [c.get("field") for c in changes]

        # `enabled` and `status` move together via Evaluation.save() coercion, and
        # both are valuable in the audit trail: `enabled` reflects user intent,
        # `status` reflects system state (ACTIVE / PAUSED / ERROR).
        self.assertIn("enabled", field_names)
        self.assertIn("status", field_names)

    def test_soft_delete_logs_as_deleted_activity(self):
        evaluation = self._create_evaluation()
        self.clear_activity_logs()

        self._update_evaluation(evaluation["id"], {"deleted": True})

        logs = self.get_activity_logs_for_item("Evaluation", evaluation["id"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].activity, "deleted")

    def test_replacing_model_configuration_logs_old_to_new_diff(self):
        # The SET_NULL cascade from deleting the old LLMModelConfiguration would null
        # Evaluation.model_configuration_id before ModelActivityMixin snapshots before_update.
        # The serializer must defer the cascade until after save() so the diff is correct.
        evaluation = self._create_evaluation(
            model_configuration={"provider": "openai", "model": "gpt-5-mini", "provider_key_id": None}
        )
        old_config_id = Evaluation.objects.get(id=evaluation["id"]).model_configuration_id
        self.assertIsNotNone(old_config_id)
        self.clear_activity_logs()

        self._update_evaluation(
            evaluation["id"],
            {"model_configuration": {"provider": "openai", "model": "gpt-5", "provider_key_id": None}},
        )

        new_config_id = Evaluation.objects.get(id=evaluation["id"]).model_configuration_id
        self.assertIsNotNone(new_config_id)
        self.assertNotEqual(new_config_id, old_config_id)

        logs = self.get_activity_logs_for_item("Evaluation", evaluation["id"])
        self.assertEqual(len(logs), 1)
        changes = logs[0].detail.get("changes", [])
        model_config_change = next((c for c in changes if c.get("field") == "model_configuration"), None)
        self.assertIsNotNone(model_config_change, f"Expected model_configuration change in {changes}")
        assert model_config_change is not None
        self.assertEqual(model_config_change["before"]["id"], str(old_config_id))
        self.assertEqual(model_config_change["before"]["model"], "gpt-5-mini")
        self.assertEqual(model_config_change["after"]["id"], str(new_config_id))
        self.assertEqual(model_config_change["after"]["model"], "gpt-5")

    def _create_provider_key(self, **overrides: Any) -> LLMProviderKey:
        defaults: dict[str, Any] = {
            "team": self.team,
            "provider": "openai",
            "name": "Key",
            "state": LLMProviderKey.State.OK,
            "encrypted_config": {"api_key": "sk-test"},
            "created_by": self.user,
        }
        defaults.update(overrides)
        return LLMProviderKey.objects.create(**defaults)

    def _create_evaluation_orm(self, **overrides: Any) -> Evaluation:
        defaults: dict[str, Any] = {
            "team": self.team,
            "name": "Eval",
            "evaluation_type": "llm_judge",
            "output_type": "boolean",
        }
        defaults.update(overrides)
        return Evaluation.objects.create(**defaults)

    def test_assigning_provider_key_clears_error_status_in_activity_log(self):
        # An errored eval cleared via provider-key assignment goes through QuerySet.update(), which
        # bypasses ModelActivityMixin.save(). The viewset must log the status transition explicitly.
        key = self._create_provider_key()
        mc = LLMModelConfiguration.objects.create(team=self.team, provider="openai", model="gpt-5-mini")
        evaluation = self._create_evaluation_orm(
            model_configuration=mc,
            enabled=False,
            status="error",
            status_reason="provider_key_deleted",
        )
        self.clear_activity_logs()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{key.id}/assign/",
            {"evaluation_ids": [str(evaluation.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        logs = self.get_activity_logs_for_item("Evaluation", str(evaluation.id))
        self.assertEqual(len(logs), 1)
        fields = {c["field"]: c for c in logs[0].detail["changes"]}
        self.assertEqual(fields["status"]["before"], "error")
        self.assertEqual(fields["status"]["after"], "paused")
        self.assertEqual(fields["status_reason"]["before"], "provider_key_deleted")
        self.assertIsNone(fields["status_reason"]["after"])
        self.assertNotIn("enabled", fields)  # error -> paused both have enabled=False

    def test_deleting_provider_key_logs_active_to_error_transition(self):
        key = self._create_provider_key()
        mc = LLMModelConfiguration.objects.create(
            team=self.team, provider="openai", model="gpt-5-mini", provider_key=key
        )
        evaluation = self._create_evaluation_orm(model_configuration=mc, enabled=True)
        self.assertEqual(evaluation.status, "active")
        self.clear_activity_logs()

        response = self.client.delete(f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{key.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        logs = self.get_activity_logs_for_item("Evaluation", str(evaluation.id))
        self.assertEqual(len(logs), 1)
        fields = {c["field"]: c for c in logs[0].detail["changes"]}
        self.assertEqual(
            fields["enabled"],
            {"type": "Evaluation", "action": "changed", "field": "enabled", "before": True, "after": False},
        )
        self.assertEqual(fields["status"]["before"], "active")
        self.assertEqual(fields["status"]["after"], "error")
        self.assertEqual(fields["status_reason"]["after"], "provider_key_deleted")
