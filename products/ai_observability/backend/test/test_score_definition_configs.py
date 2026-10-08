import unittest

from parameterized import parameterized
from rest_framework import serializers

from products.ai_observability.backend.score_definition_configs import build_score_definition_config_serializer


class TestScoreDefinitionConfigValidation(unittest.TestCase):
    @parameterized.expand(
        [
            ("unknown_category", {"categories": ["missing"]}),
            ("duplicate_category", {"categories": ["good", "good"]}),
            ("empty_single", {"categories": []}),
            ("missing_categories", {}),
            ("unknown_key", {"categories": ["good"], "operator": "any"}),
        ]
    )
    def test_rejects_invalid_categorical_passing_rules(self, _name: str, rule: dict[str, list[str] | str]) -> None:
        serializer = build_score_definition_config_serializer(
            "categorical",
            data={
                "options": [{"key": "good", "label": "Good"}],
                "passing_rule": rule,
            },
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("passing_rule", serializer.errors)

    @parameterized.expand(
        [
            (
                "categorical_requires_options",
                "categorical",
                {"options": []},
                {"options": ["Provide at least one categorical option."]},
            ),
            (
                "categorical_requires_unique_keys",
                "categorical",
                {"options": [{"key": "good", "label": "Good"}, {"key": "good", "label": "Bad"}]},
                {"options": ["Categorical option keys must be unique."]},
            ),
            (
                "categorical_single_rejects_min_selections",
                "categorical",
                {
                    "options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}],
                    "min_selections": 1,
                },
                {"min_selections": ["`min_selections` is only supported when `selection_mode` is `multiple`."]},
            ),
            (
                "categorical_multiple_requires_min_to_fit_options",
                "categorical",
                {
                    "options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}],
                    "selection_mode": "multiple",
                    "min_selections": 3,
                },
                {"min_selections": ["Ensure `min_selections` is less than or equal to the number of options."]},
            ),
            (
                "categorical_multiple_requires_max_to_fit_options",
                "categorical",
                {
                    "options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}],
                    "selection_mode": "multiple",
                    "max_selections": 3,
                },
                {"max_selections": ["Ensure `max_selections` is less than or equal to the number of options."]},
            ),
            (
                "categorical_multiple_requires_max_above_min",
                "categorical",
                {
                    "options": [
                        {"key": "good", "label": "Good"},
                        {"key": "mixed", "label": "Mixed"},
                        {"key": "bad", "label": "Bad"},
                    ],
                    "selection_mode": "multiple",
                    "min_selections": 3,
                    "max_selections": 2,
                },
                {"max_selections": ["Ensure `max_selections` is greater than or equal to `min_selections`."]},
            ),
            (
                "numeric_requires_positive_step",
                "numeric",
                {"step": 0},
                {"step": ["Ensure `step` is greater than 0."]},
            ),
            (
                "numeric_requires_max_above_min",
                "numeric",
                {"min": 5, "max": 2},
                {"max": ["Ensure `max` is greater than or equal to `min`."]},
            ),
        ]
    )
    def test_invalid_configs_raise_validation_error(
        self, _name: str, kind: str, payload: dict, expected_detail: dict[str, list[str]]
    ) -> None:
        serializer = build_score_definition_config_serializer(kind, data=payload)

        with self.assertRaises(serializers.ValidationError) as err:
            serializer.is_valid(raise_exception=True)

        detail = err.exception.detail
        assert isinstance(detail, dict)
        self.assertEqual(
            {field: [str(item) for item in details] for field, details in detail.items()},
            expected_detail,
        )

    @parameterized.expand(
        [
            (
                "categorical",
                "categorical",
                {"options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}]},
            ),
            (
                "categorical_multiple",
                "categorical",
                {
                    "options": [
                        {"key": "good", "label": "Good"},
                        {"key": "mixed", "label": "Mixed"},
                        {"key": "bad", "label": "Bad"},
                    ],
                    "selection_mode": "multiple",
                    "min_selections": 1,
                    "max_selections": 2,
                },
            ),
            (
                "categorical_passing",
                "categorical",
                {"options": [{"key": "good", "label": "Good"}], "passing_rule": {"categories": ["good"]}},
            ),
            (
                "categorical_neutral",
                "categorical",
                {"options": [{"key": "good", "label": "Good"}], "passing_rule": None},
            ),
            (
                "categorical_no_passing_categories",
                "categorical",
                {
                    "options": [{"key": "good", "label": "Good"}],
                    "selection_mode": "multiple",
                    "passing_rule": {"categories": []},
                },
            ),
            ("numeric", "numeric", {"min": 0, "max": 5, "step": 1}),
            (
                "numeric_passing",
                "numeric",
                {"min": 0, "max": 5, "step": 1, "passing_rule": {"operator": "gte", "threshold": 2.5}},
            ),
            ("numeric_neutral", "numeric", {"passing_rule": None}),
            ("boolean", "boolean", {"true_label": "Yes", "false_label": "No"}),
            ("boolean_true_passes", "boolean", {"true_is_failure": False}),
            ("boolean_true_fails", "boolean", {"true_is_failure": True}),
            ("boolean_default_polarity", "boolean", {"true_is_failure": None}),
            ("boolean_legacy", "boolean", {}),
        ]
    )
    def test_valid_configs_pass_validation(self, _name: str, kind: str, payload: dict) -> None:
        serializer = build_score_definition_config_serializer(kind, data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, payload)

    @parameterized.expand(
        [
            ("below_minimum", {"operator": "gte", "threshold": -1}),
            ("above_maximum", {"operator": "lte", "threshold": 6}),
            ("unknown_operator", {"operator": "gt", "threshold": 3}),
            ("missing_threshold", {"operator": "gte"}),
            ("missing_operator", {"threshold": 3}),
            ("unknown_key", {"operator": "gte", "threshold": 3, "unexpected": True}),
            ("boolean_threshold", {"operator": "gte", "threshold": True}),
            ("string_threshold", {"operator": "gte", "threshold": "3"}),
            ("nan_threshold", {"operator": "gte", "threshold": float("nan")}),
            ("infinite_threshold", {"operator": "gte", "threshold": float("inf")}),
            ("overflowing_threshold", {"operator": "gte", "threshold": 10**400}),
        ]
    )
    def test_rejects_invalid_numeric_passing_rule(self, _name: str, rule: dict[str, object]) -> None:
        serializer = build_score_definition_config_serializer(
            "numeric", data={"min": 0, "max": 5, "passing_rule": rule}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("passing_rule", serializer.errors)
