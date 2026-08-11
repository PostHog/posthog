"""Polarity behavior of boolean evaluation report outcome definitions."""

import json

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.temporal.ai_observability.eval_reports.output_types import get_outcome_definition
from posthog.temporal.ai_observability.eval_reports.report_agent.prompts import build_eval_report_system_prompt
from posthog.temporal.ai_observability.eval_reports.report_agent.tools import _outcome_for_result, get_summary_metrics

_get_summary_metrics_fn = get_summary_metrics.func  # type: ignore[attr-defined]


class TestBooleanPolarity(SimpleTestCase):
    def test_default_polarity_maps_true_to_pass(self):
        definition = get_outcome_definition("boolean")
        self.assertIn("properties.$ai_evaluation_result = true", definition.outcome_predicates["pass"])
        self.assertIn("properties.$ai_evaluation_result = false", definition.outcome_predicates["fail"])
        self.assertEqual(definition.result_labels, {True: "pass", False: "fail"})

    def test_detector_polarity_maps_true_to_fail(self):
        definition = get_outcome_definition("boolean", true_is_pass=False)
        self.assertIn("properties.$ai_evaluation_result = false", definition.outcome_predicates["pass"])
        self.assertIn("properties.$ai_evaluation_result = true", definition.outcome_predicates["fail"])
        self.assertEqual(definition.result_labels, {True: "fail", False: "pass"})

    def test_outcome_for_result_flips_with_polarity(self):
        detector = get_outcome_definition("boolean", true_is_pass=False)
        self.assertEqual(_outcome_for_result("boolean", True, definition=detector), "fail")
        self.assertEqual(_outcome_for_result("boolean", False, definition=detector), "pass")
        # Not-applicable still wins regardless of polarity.
        self.assertEqual(_outcome_for_result("boolean", True, applicable=False, definition=detector), "na")

    def test_prompt_describes_detector_polarity(self):
        prompt = build_eval_report_system_prompt(
            evaluation_name="Struggle detector",
            evaluation_description="",
            evaluation_prompt="",
            evaluation_type="llm_judge",
            output_type="boolean",
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
            true_is_pass=False,
        )
        self.assertIn("detector-style", prompt)
        self.assertIn("reported as a **fail**", prompt)

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    def test_detector_summary_metrics_count_pass_from_false_results(self, mock_execute_hogql):
        # 18 healthy (false) and 80 flagged (true) results: a detector reports the 80 as fails.
        mock_execute_hogql.side_effect = [
            [[18, 80, 2, 100]],
            [[2, 7, 1, 10]],
        ]
        state = {
            "team_id": 1,
            "evaluation_id": "eval-id",
            "output_type": "boolean",
            "true_is_pass": False,
            "period_start": "2026-04-08T14:00:00+00:00",
            "period_end": "2026-04-08T15:00:00+00:00",
            "previous_period_start": "2026-04-08T13:00:00+00:00",
        }

        result = json.loads(_get_summary_metrics_fn(state=state))

        self.assertEqual(result["current_period"]["result_counts"], {"pass": 18, "fail": 80, "na": 2})
        self.assertEqual(result["current_period"]["pass_rate"], 18.37)
        pass_count_column = mock_execute_hogql.call_args_list[0].args[1].split("as fail_count")[0]
        self.assertIn("properties.$ai_evaluation_result = false", pass_count_column)
