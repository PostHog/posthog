from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.ai_observability.backend.models.evaluations import Evaluation, EvaluationStatus, EvaluationStatusReason

REJECTED_HOG_SOURCE = "let output := output\nreturn true"


class TestEvaluationModel(BaseTest):
    def test_compiles_bytecode_for_conditions_with_properties(self):
        """
        Evaluations should compile bytecode for conditions with properties on save
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "cond-1",
                    "rollout_percentage": 100,
                    "properties": [
                        {"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}
                    ],
                }
            ],
        )

        evaluation.refresh_from_db()

        self.assertEqual(len(evaluation.conditions), 1)
        self.assertIn("bytecode", evaluation.conditions[0])
        self.assertIsNotNone(evaluation.conditions[0]["bytecode"])
        self.assertIsInstance(evaluation.conditions[0]["bytecode"], list)

    @parameterized.expand(
        [
            (f"{broken}_{action}", broken, updates, field, expected)
            for broken in ("condition", "hog_source")
            for action, updates, field, expected in [
                ("set_status", None, "status", EvaluationStatus.ERROR),
                ("pause", {"enabled": False}, "enabled", False),
                ("delete", {"deleted": True}, "deleted", True),
            ]
        ]
    )
    def test_save_without_code_change_succeeds_when_stored_code_no_longer_compiles(
        self, _name, broken, updates, field, expected
    ):
        evaluation = self._create_hog_evaluation()
        stored_bytecode = evaluation.evaluation_config["bytecode"]
        if broken == "hog_source":
            self._store_rejected_hog_source(evaluation)

        condition_result = (
            {"bytecode": None, "bytecode_error": "Invalid property filter"}
            if broken == "condition"
            else {"bytecode": ["_H", 1], "bytecode_error": None}
        )
        with patch(
            "products.cdp.backend.filters.compile_filters_bytecode", return_value=condition_result
        ) as mock_compile:
            if updates is None:
                evaluation.set_status(EvaluationStatus.ERROR, EvaluationStatusReason.HOG_ERROR)
            else:
                for key, value in updates.items():
                    setattr(evaluation, key, value)
                evaluation.save()
            mock_compile.assert_called_once()

        evaluation.refresh_from_db()
        self.assertEqual(getattr(evaluation, field), expected)
        self.assertEqual(evaluation.evaluation_config["bytecode"], stored_bytecode)

    def test_full_save_rejects_filter_edited_in_place_after_status_only_save(self):
        evaluation = self._create_hog_evaluation()

        evaluation.conditions[0]["properties"].append({"type": "hogql", "key": "(select 1)"})
        evaluation.set_status(EvaluationStatus.ERROR, EvaluationStatusReason.HOG_ERROR)

        with self.assertRaises(ValidationError):
            evaluation.save()
        evaluation.refresh_from_db()
        self.assertEqual(evaluation.conditions[0]["properties"], [])

    def test_full_save_keeps_stored_bytecode_when_resubmitted_hog_source_no_longer_compiles(self):
        evaluation = self._create_hog_evaluation()
        stored_bytecode = evaluation.evaluation_config["bytecode"]
        self._store_rejected_hog_source(evaluation)

        evaluation.evaluation_config = {"source": REJECTED_HOG_SOURCE}
        evaluation.save()

        evaluation.refresh_from_db()
        self.assertEqual(evaluation.evaluation_config["bytecode"], stored_bytecode)

    @parameterized.expand(
        [
            ("edit_source_in_place", lambda e: e.evaluation_config.update(source="let x := x\nreturn false")),
            ("reenable", lambda e: setattr(e, "enabled", True)),
        ]
    )
    def test_full_save_rejects_stored_hog_source_that_no_longer_compiles(self, _name, change):
        evaluation = self._create_hog_evaluation()
        self._store_rejected_hog_source(evaluation)
        evaluation.set_status(EvaluationStatus.ERROR, EvaluationStatusReason.HOG_ERROR)

        change(evaluation)
        with self.assertRaises(ValidationError):
            evaluation.save()

        evaluation.refresh_from_db()
        self.assertEqual(evaluation.status, EvaluationStatus.ERROR)
        self.assertEqual(evaluation.evaluation_config["source"], REJECTED_HOG_SOURCE)

    def _create_hog_evaluation(self) -> Evaluation:
        return Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            enabled=True,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

    def _store_rejected_hog_source(self, evaluation: Evaluation) -> None:
        Evaluation.objects.filter(id=evaluation.id).update(
            evaluation_config={**evaluation.evaluation_config, "source": REJECTED_HOG_SOURCE}
        )
        evaluation.refresh_from_db()

    def test_handles_empty_properties_list(self):
        """
        Conditions with empty properties should still be saved correctly
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "cond-1",
                    "rollout_percentage": 100,
                    "properties": [],
                }
            ],
        )

        evaluation.refresh_from_db()

        self.assertEqual(len(evaluation.conditions), 1)
        self.assertEqual(evaluation.conditions[0]["properties"], [])
        self.assertIn("bytecode", evaluation.conditions[0])

    def test_compiles_bytecode_for_multiple_conditions(self):
        """
        All conditions should have their bytecode compiled independently
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "cond-1",
                    "rollout_percentage": 100,
                    "properties": [
                        {"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}
                    ],
                },
                {
                    "id": "cond-2",
                    "rollout_percentage": 50,
                    "properties": [{"key": "name", "value": "test", "operator": "exact", "type": "person"}],
                },
            ],
        )

        evaluation.refresh_from_db()

        self.assertEqual(len(evaluation.conditions), 2)
        self.assertIn("bytecode", evaluation.conditions[0])
        self.assertIn("bytecode", evaluation.conditions[1])
        self.assertIsNotNone(evaluation.conditions[0]["bytecode"])
        self.assertIsNotNone(evaluation.conditions[1]["bytecode"])

    @patch("posthog.plugins.plugin_server_api.reload_evaluations_on_workers")
    def test_sends_reload_signal_on_save(self, mock_reload):
        """
        Django signal should trigger reload on workers when evaluation is saved
        """
        with self.captureOnCommitCallbacks(execute=True):
            evaluation = Evaluation.objects.create(
                team=self.team,
                name="Test Evaluation",
                evaluation_type="llm_judge",
                evaluation_config={"prompt": "Test prompt"},
                output_type="boolean",
                output_config={},
                enabled=True,
                created_by=self.user,
                conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
            )

        mock_reload.assert_called_once_with(team_id=self.team.id, evaluation_ids=[str(evaluation.id)])

    @patch("posthog.plugins.plugin_server_api.reload_evaluations_on_workers")
    def test_sends_reload_signal_on_update(self, mock_reload):
        """
        Django signal should trigger reload on workers when evaluation is updated
        """
        with self.captureOnCommitCallbacks(execute=True):
            evaluation = Evaluation.objects.create(
                team=self.team,
                name="Original Name",
                evaluation_type="llm_judge",
                evaluation_config={"prompt": "Test prompt"},
                output_type="boolean",
                output_config={},
                enabled=True,
                created_by=self.user,
                conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
            )

        mock_reload.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            evaluation.name = "Updated Name"
            evaluation.save()

        mock_reload.assert_called_once_with(team_id=self.team.id, evaluation_ids=[str(evaluation.id)])

    def test_hog_evaluation_compiles_source_to_bytecode(self):
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Hog Eval",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

        evaluation.refresh_from_db()

        self.assertIn("bytecode", evaluation.evaluation_config)
        self.assertIsInstance(evaluation.evaluation_config["bytecode"], list)
        self.assertTrue(len(evaluation.evaluation_config["bytecode"]) > 0)

    def test_hog_evaluation_compiles_null_safe_comparisons(self):
        from posthog.temporal.ai_observability.run_evaluation import run_hog_eval

        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Hog Eval",
            evaluation_type="hog",
            evaluation_config={"source": "return properties.missing <= 1.0"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

        result = run_hog_eval(
            evaluation.evaluation_config["bytecode"],
            {
                "uuid": "event-id",
                "event": "$ai_generation",
                "properties": {},
                "distinct_id": "user-1",
            },
        )

        self.assertFalse(result["verdict"])
        self.assertIsNone(result["error"])

    @parameterized.expand(
        [
            ("syntax_error", "this is not valid hog {{{{"),
            ("local_read_in_own_declaration", REJECTED_HOG_SOURCE),
        ]
    )
    def test_hog_evaluation_invalid_source_raises_validation_error(self, _name, source):
        with self.assertRaises(ValidationError):
            Evaluation.objects.create(
                team=self.team,
                name="Bad Hog Eval",
                evaluation_type="hog",
                evaluation_config={"source": source},
                output_type="boolean",
                output_config={},
                enabled=True,
                created_by=self.user,
                conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
            )

    def test_hog_evaluation_empty_source_rejected(self):
        with self.assertRaises(ValidationError):
            Evaluation.objects.create(
                team=self.team,
                name="Empty Hog Eval",
                evaluation_type="hog",
                evaluation_config={"source": ""},
                output_type="boolean",
                output_config={},
                enabled=True,
                created_by=self.user,
                conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
            )

    def test_hog_evaluation_recompiles_bytecode_on_update(self):
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Hog Eval",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

        evaluation.refresh_from_db()
        original_bytecode = evaluation.evaluation_config["bytecode"]

        evaluation.evaluation_config = {"source": "return false"}
        evaluation.save()
        evaluation.refresh_from_db()

        self.assertIn("bytecode", evaluation.evaluation_config)
        self.assertNotEqual(evaluation.evaluation_config["bytecode"], original_bytecode)

    def test_sentiment_evaluation_defaults_to_user_messages_source(self):
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Sentiment Eval",
            evaluation_type="sentiment",
            evaluation_config={},
            output_type="sentiment",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
        )

        evaluation.refresh_from_db()

        self.assertEqual(evaluation.evaluation_config, {"source": "user_messages"})
        self.assertEqual(evaluation.output_config, {})

    def test_unsupported_evaluation_output_type_combination_rejected(self):
        with self.assertRaises(ValidationError):
            Evaluation.objects.create(
                team=self.team,
                name="Bad Eval",
                evaluation_type="llm_judge",
                evaluation_config={},
                output_type="sentiment",
                output_config={},
                enabled=True,
                created_by=self.user,
                conditions=[{"id": "cond-1", "rollout_percentage": 100, "properties": []}],
            )

    def test_preserves_other_condition_fields(self):
        """
        Other condition fields (id, rollout_percentage) should be preserved during save
        """
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[
                {
                    "id": "my-custom-id",
                    "rollout_percentage": 75,
                    "properties": [],
                }
            ],
        )

        evaluation.refresh_from_db()

        self.assertEqual(evaluation.conditions[0]["id"], "my-custom-id")
        self.assertEqual(evaluation.conditions[0]["rollout_percentage"], 75)


class TestEvaluationStatusCoercion(BaseTest):
    def _create(self, **overrides) -> Evaluation:
        defaults: dict = {
            "team": self.team,
            "name": "Test",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "p"},
            "output_type": "boolean",
            "output_config": {},
            "created_by": self.user,
            "conditions": [],
        }
        defaults.update(overrides)
        return Evaluation.objects.create(**defaults)

    @parameterized.expand(
        [
            (True, EvaluationStatus.ACTIVE),
            (False, EvaluationStatus.PAUSED),
        ]
    )
    def test_new_row_status_derived_from_enabled(self, enabled, expected_status):
        evaluation = self._create(enabled=enabled)
        self.assertEqual(evaluation.status, expected_status)
        self.assertIsNone(evaluation.status_reason)

    def test_flipping_enabled_false_on_active_row_transitions_to_paused(self):
        evaluation = self._create(enabled=True)
        evaluation.enabled = False
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.PAUSED)
        self.assertFalse(evaluation.enabled)

    def test_flipping_enabled_true_on_errored_row_transitions_to_active_and_clears_reason(self):
        evaluation = self._create(enabled=False)
        evaluation.status = EvaluationStatus.ERROR
        evaluation.status_reason = EvaluationStatusReason.PROVIDER_KEY_REQUIRED
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.ERROR)

        evaluation.enabled = True
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.ACTIVE)
        self.assertTrue(evaluation.enabled)
        self.assertIsNone(evaluation.status_reason)

    def test_setting_status_error_requires_reason(self):
        evaluation = self._create(enabled=True)
        evaluation.status = EvaluationStatus.ERROR
        with self.assertRaises(ValidationError):
            evaluation.save()

    def test_setting_status_error_with_reason_forces_enabled_false(self):
        evaluation = self._create(enabled=True)
        evaluation.status = EvaluationStatus.ERROR
        evaluation.status_reason = EvaluationStatusReason.PROVIDER_KEY_REQUIRED
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.ERROR)
        self.assertFalse(evaluation.enabled)
        self.assertEqual(evaluation.status_reason, EvaluationStatusReason.PROVIDER_KEY_REQUIRED)

    def test_paused_status_clears_any_stale_status_reason(self):
        evaluation = self._create(enabled=True)
        evaluation.status = EvaluationStatus.ERROR
        evaluation.status_reason = EvaluationStatusReason.PROVIDER_KEY_REQUIRED
        evaluation.status_reason_detail = "No provider API key configured."
        evaluation.save()

        evaluation.status = EvaluationStatus.PAUSED
        evaluation.save()
        self.assertIsNone(evaluation.status_reason)
        self.assertIsNone(evaluation.status_reason_detail)

    def test_set_status_helper_transitions_all_three_fields(self):
        evaluation = self._create(enabled=True)
        evaluation.set_status(
            EvaluationStatus.ERROR,
            EvaluationStatusReason.HOG_ERROR,
            "Must return boolean, got int: 42",
        )
        evaluation.refresh_from_db()
        self.assertEqual(evaluation.status, EvaluationStatus.ERROR)
        self.assertEqual(evaluation.status_reason, EvaluationStatusReason.HOG_ERROR)
        self.assertEqual(evaluation.status_reason_detail, "Must return boolean, got int: 42")
        self.assertFalse(evaluation.enabled)

    def test_refresh_from_db_resets_change_tracking_baseline(self):
        """After refresh_from_db, a subsequent edit must be compared against DB state — not the
        pre-refresh in-memory snapshot. Without this, a user toggling enabled=True after refresh on
        an errored instance would be silently coerced back to enabled=False."""
        evaluation = self._create(enabled=True)
        # Simulate a system transition happening elsewhere (another worker, another request, etc.).
        Evaluation.objects.filter(id=evaluation.id).update(
            enabled=False, status=EvaluationStatus.ERROR, status_reason=EvaluationStatusReason.PROVIDER_KEY_REQUIRED
        )

        evaluation.refresh_from_db()
        # User re-enables from the now-refreshed state.
        evaluation.enabled = True
        evaluation.save()
        self.assertEqual(evaluation.status, EvaluationStatus.ACTIVE)
        self.assertTrue(evaluation.enabled)
        self.assertIsNone(evaluation.status_reason)
