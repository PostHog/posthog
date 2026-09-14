from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.ai_observability.eval_reports.output_types import (
    SUPPORTED_EVAL_REPORT_OUTPUT_TYPES,
    get_outcome_definition,
)


class TestOutcomeDefinitions(SimpleTestCase):
    def test_absent_polarity_keeps_true_as_the_pass(self):
        definition = get_outcome_definition("boolean")
        self.assertIn("properties.$ai_evaluation_result = true", definition.outcome_predicates["pass"])
        self.assertIn("properties.$ai_evaluation_result = false", definition.outcome_predicates["fail"])
        self.assertEqual(definition.label_for(True), "pass")
        self.assertEqual(definition.label_for(False), "fail")

    def test_detector_polarity_makes_true_the_fail(self):
        definition = get_outcome_definition("boolean", true_is_failure=True)
        self.assertIn("properties.$ai_evaluation_result = false", definition.outcome_predicates["pass"])
        self.assertIn("properties.$ai_evaluation_result = true", definition.outcome_predicates["fail"])
        self.assertEqual(definition.label_for(True), "fail")
        self.assertEqual(definition.label_for(False), "pass")

    @parameterized.expand([(False,), (True,)])
    def test_not_applicable_wins_over_polarity(self, true_is_failure: bool):
        definition = get_outcome_definition("boolean", true_is_failure=true_is_failure)
        self.assertEqual(definition.label_for(True, applicable=False), "na")
        self.assertEqual(definition.label_for(False, applicable=False), "na")

    @parameterized.expand([(False,), (True,)])
    def test_polarity_does_not_touch_sentiment(self, true_is_failure: bool):
        definition = get_outcome_definition("sentiment", true_is_failure=true_is_failure)
        self.assertEqual(definition.outcomes, ("positive", "neutral", "negative"))
        self.assertEqual(definition.label_for("negative"), "negative")
        self.assertIsNone(definition.label_for("nonsense"))

    @parameterized.expand([(None,), ("true",), (2,)])
    def test_non_boolean_result_has_no_label(self, result: object):
        definition = get_outcome_definition("boolean")
        self.assertIsNone(definition.label_for(result))

    def test_integer_boolean_result_gets_a_label(self):
        # A ClickHouse UInt8 column can hand back an int for a logically boolean result.
        definition = get_outcome_definition("boolean")
        self.assertEqual(definition.label_for(1), "pass")
        self.assertEqual(definition.label_for(0), "fail")

    def test_supported_types_are_derived_from_the_builders(self):
        self.assertEqual(set(SUPPORTED_EVAL_REPORT_OUTPUT_TYPES), {"boolean", "sentiment"})
        for output_type in SUPPORTED_EVAL_REPORT_OUTPUT_TYPES:
            self.assertIsNotNone(get_outcome_definition(output_type))

    def test_unsupported_type_raises(self):
        with self.assertRaises(ValueError):
            get_outcome_definition("numeric")


class TestReportPromptPolarity(SimpleTestCase):
    def _prompt(self, *, true_is_failure: bool) -> str:
        from posthog.temporal.ai_observability.eval_reports.report_agent.prompts import build_eval_report_system_prompt

        return build_eval_report_system_prompt(
            evaluation_name="Struggle detector",
            evaluation_description="",
            evaluation_prompt="",
            evaluation_type="llm_judge",
            output_type="boolean",
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
            true_is_failure=true_is_failure,
        )

    def test_detector_prompt_says_a_true_result_is_reported_as_a_fail(self):
        prompt = self._prompt(true_is_failure=True)
        self.assertIn("reported as a fail", prompt)

    def test_default_prompt_keeps_the_pass_on_true_story(self):
        prompt = self._prompt(true_is_failure=False)
        self.assertIn("satisfied the configured criteria", prompt)
        self.assertNotIn("reported as a fail", prompt)
