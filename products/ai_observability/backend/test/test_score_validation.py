import math
from decimal import Decimal
from functools import reduce
from operator import add

import unittest

from parameterized import parameterized

from products.ai_observability.backend.score_validation import validate_score_value


class TestScoreValueValidation(unittest.TestCase):
    @parameterized.expand(
        [
            ("decimal_on_step", Decimal("0.3"), {"step": 0.1}, None),
            (
                "decimal_off_step",
                Decimal("0.3000001"),
                {"step": 0.1},
                "Ensure this value increments by 0.1.",
            ),
            ("decimal_tiny_step", Decimal("1000.000000"), {"step": 1e-30}, None),
            (
                "decimal_tiny_off_step",
                Decimal("1000.000000"),
                {"step": 3e-30},
                "Ensure this value increments by 3E-30.",
            ),
            ("float_rounding", 0.1 + 0.2, {"step": 0.1}, None),
            ("float_subtraction_rounding", 1.1 - 1.0, {"step": 0.1}, None),
            ("float_accumulated_rounding", reduce(add, [0.1] * 100), {"step": 0.1}, None),
            ("float_at_step_tolerance", 0.3000001, {"step": 0.1}, None),
            (
                "float_beyond_step_tolerance",
                math.nextafter(0.3000001, math.inf),
                {"step": 0.1},
                "Ensure this value increments by 0.1.",
            ),
            ("float_off_step", 0.300001, {"step": 0.1}, "Ensure this value increments by 0.1."),
            ("float_negative_rounding", -0.1 - 0.2, {"step": 0.1}, None),
            ("float_step_from_minimum", 0.15 + 0.3, {"min": 0.15, "step": 0.1}, None),
            (
                "float_step_uses_minimum",
                0.4,
                {"min": 0.15, "step": 0.1},
                "Ensure this value increments by 0.1.",
            ),
            ("float_no_six_decimal_limit", 0.123456789, {}, None),
            ("float_large_on_step", float(2**52), {"step": 2}, None),
            ("float_large_off_step", float(2**52 + 1), {"step": 2}, "Ensure this value increments by 2."),
            ("float_large_negative_off_step", -float(2**52 + 1), {"step": 2}, "Ensure this value increments by 2."),
            (
                "float_step_below_precision",
                0.1 + 0.2,
                {"step": 1e-16},
                "Ensure this value increments by 1E-16.",
            ),
            ("float_extreme_step_ratio", 1e308, {"step": 1e-308}, None),
            ("float_tiny_step", 3e-308, {"step": 1e-308}, None),
            ("float_tiny_off_step", 3.1e-308, {"step": 1e-308}, "Ensure this value increments by 1E-308."),
            ("float_subnormal", 5e-324, {"step": 5e-324}, None),
            ("float_exact_maximum", 0.3, {"max": 0.3}, None),
            (
                "float_above_maximum",
                math.nextafter(0.3, math.inf),
                {"max": 0.3},
                "Ensure this value is less than or equal to 0.3.",
            ),
            (
                "float_below_minimum",
                math.nextafter(0.3, -math.inf),
                {"min": 0.3},
                "Ensure this value is greater than or equal to 0.3.",
            ),
            ("zero", 0.0, {"min": 0, "max": 1, "step": 0.1}, None),
            ("non_finite_value", math.inf, {}, "Provide a finite numeric value."),
            (
                "non_finite_config",
                0.5,
                {"step": math.nan},
                "This scorer has an invalid numeric configuration.",
            ),
        ]
    )
    def test_numeric_validation(
        self, _name: str, value: Decimal | float, config: dict[str, object], expected_error: str | None
    ) -> None:
        self.assertEqual(
            validate_score_value("numeric", config, numeric_value=value),
            {"numeric_value": expected_error} if expected_error else {},
        )

    @parameterized.expand(
        [
            ("too_few", ["good"], {"categorical_values": "Select at least 2 categorical options."}),
            ("minimum_satisfied", ["good", "accurate"], {}),
            ("unknown_key", ["good", "unknown"], {"categorical_values": "Select valid categorical option keys."}),
        ]
    )
    def test_categorical_minimum(self, _name: str, values: list[str], expected_errors: dict[str, str]) -> None:
        self.assertEqual(
            validate_score_value(
                "categorical",
                {
                    "options": [{"key": "good"}, {"key": "accurate"}],
                    "selection_mode": "multiple",
                    "min_selections": 2,
                },
                categorical_values=values,
            ),
            expected_errors,
        )

    @parameterized.expand(
        [
            ("categorical", "categorical_values"),
            ("numeric", "numeric_value"),
            ("boolean", "boolean_value"),
        ]
    )
    def test_missing_value_reports_kind_specific_field(self, kind: str, field: str) -> None:
        self.assertEqual(validate_score_value(kind, {}), {field: f"This scorer requires `{field}`."})

    def test_false_is_a_score(self) -> None:
        self.assertEqual(validate_score_value("boolean", {}, boolean_value=False), {})
