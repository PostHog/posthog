from typing import Any

from rest_framework import status

from posthog.test.activity_log_utils import ActivityLogTestHelper

from products.llm_analytics.backend.models.evaluations import Evaluation


def _create_evaluation_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "Test Evaluation",
        "description": "Initial",
        "enabled": True,
        "evaluation_type": "llm_judge",
        "evaluation_config": {"prompt": "Test prompt"},
        "output_type": "boolean",
        "output_config": {},
        "conditions": [
            {"id": "cond-1", "rollout_percentage": 25, "properties": []},
        ],
    }
    payload.update(overrides)
    return payload


class TestEvaluationActivityLogging(ActivityLogTestHelper):
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
        if logs:
            changes = logs[0].detail.get("changes", [])
            field_names = [c.get("field") for c in changes]
            self.assertNotIn("conditions", field_names)

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
