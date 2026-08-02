"""Tests for boolean outcome-predicate polarity.

A detector-style judge prompt ("return true when the agent struggled") has `true` as the
bad outcome. Without a polarity switch, `get_outcome_definition` always counted
`$ai_evaluation_result = true` as "pass", so every detector eval's reports came out
backwards relative to what the prompt itself means.
"""

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.ai_observability.eval_reports.output_types import (
    DEFAULT_BOOLEAN_POLARITY,
    TRUE_IS_FAIL,
    TRUE_IS_PASS,
    get_outcome_definition,
)


class TestBooleanOutcomePolarity(SimpleTestCase):
    def test_default_polarity_matches_true_is_pass(self):
        self.assertEqual(DEFAULT_BOOLEAN_POLARITY, TRUE_IS_PASS)

    @parameterized.expand(
        [
            (None, "true", "false"),
            (TRUE_IS_PASS, "true", "false"),
            (TRUE_IS_FAIL, "false", "true"),
        ]
    )
    def test_pass_and_fail_predicates_track_polarity(self, polarity, expected_pass_value, expected_fail_value):
        definition = get_outcome_definition("boolean", polarity)
        self.assertIn(
            f"properties.$ai_evaluation_result = {expected_pass_value}", definition.outcome_predicates["pass"]
        )
        self.assertIn(
            f"properties.$ai_evaluation_result = {expected_fail_value}", definition.outcome_predicates["fail"]
        )

    def test_polarity_does_not_change_na_predicate_or_outcome_keys(self):
        default_definition = get_outcome_definition("boolean", TRUE_IS_PASS)
        inverted_definition = get_outcome_definition("boolean", TRUE_IS_FAIL)
        self.assertEqual(default_definition.outcomes, inverted_definition.outcomes)
        self.assertEqual(
            default_definition.outcome_predicates["na"],
            inverted_definition.outcome_predicates["na"],
        )

    def test_polarity_is_ignored_for_sentiment(self):
        default_definition = get_outcome_definition("sentiment", TRUE_IS_PASS)
        inverted_definition = get_outcome_definition("sentiment", TRUE_IS_FAIL)
        self.assertEqual(default_definition, inverted_definition)
