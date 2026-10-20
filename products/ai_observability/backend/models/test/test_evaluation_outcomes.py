from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.models.evaluation_outcomes import (
    SUPPORTED_EVAL_REPORT_OUTPUT_TYPES,
    get_outcome_definition,
)


class TestOutcomeDefinitions(SimpleTestCase):
    @parameterized.expand(
        [
            (["resolved"], ["resolved"], "pass"),
            (["resolved", "incorrect"], ["resolved"], "fail"),
            (["incorrect"], ["resolved"], "fail"),
            ([], ["resolved"], "fail"),
            ([], [], "pass"),
            (["resolved"], [], "fail"),
            ([], None, None),
            (["resolved"], None, None),
        ]
    )
    def test_categorical_passing_categories(
        self, categories: list[str], passing_categories: list[str] | None, outcome: str | None
    ) -> None:
        definition = get_outcome_definition(
            "categorical",
            output_config={
                "options": [{"key": "resolved", "label": "Resolved"}, {"key": "incorrect", "label": "Incorrect"}],
                "selection_mode": "multiple",
                "passing_rule": {"categories": passing_categories} if passing_categories is not None else None,
            },
        )
        self.assertEqual(definition.label_for(categories), outcome)
        self.assertEqual(definition.label_for(None, applicable=False), "na")
        self.assertIsNone(definition.label_for(None))
        self.assertIsNone(definition.label_for("resolved"))

    @parameterized.expand(
        [
            ("gte", 6, "fail"),
            ("gte", 7, "pass"),
            ("gte", 8, "pass"),
            ("lte", 6, "pass"),
            ("lte", 7, "pass"),
            ("lte", 8, "fail"),
        ]
    )
    def test_numeric_passing_rule(self, operator, score, outcome):
        definition = get_outcome_definition(
            "numeric", output_config={"passing_rule": {"operator": operator, "threshold": 7}}
        )
        self.assertEqual(definition.label_for(score), outcome)
        self.assertEqual(definition.label_for(None, applicable=False), "na")
        self.assertIsNone(definition.label_for(True))
        self.assertIsNone(definition.label_for(float("nan")))

    def test_numeric_without_rule_has_no_pass_fail(self):
        definition = get_outcome_definition("numeric")
        self.assertIsNone(definition.label_for(0))

    def test_absent_polarity_keeps_true_as_the_pass(self):
        definition = get_outcome_definition("boolean")
        self.assertIn("properties.$ai_evaluation_result = 'true'", definition.outcome_predicates["pass"])
        self.assertIn("properties.$ai_evaluation_result = 'false'", definition.outcome_predicates["fail"])
        self.assertEqual(definition.label_for(True), "pass")
        self.assertEqual(definition.label_for(False), "fail")

    def test_detector_polarity_makes_true_the_fail(self):
        definition = get_outcome_definition("boolean", true_is_failure=True)
        self.assertIn("properties.$ai_evaluation_result = 'false'", definition.outcome_predicates["pass"])
        self.assertIn("properties.$ai_evaluation_result = 'true'", definition.outcome_predicates["fail"])
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
        self.assertEqual(set(SUPPORTED_EVAL_REPORT_OUTPUT_TYPES), {"boolean", "sentiment", "numeric", "categorical"})
        for output_type in SUPPORTED_EVAL_REPORT_OUTPUT_TYPES:
            self.assertIsNotNone(get_outcome_definition(output_type))

    def test_unsupported_type_raises(self):
        with self.assertRaises(ValueError):
            get_outcome_definition("unsupported")
