import json
from pathlib import Path
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.composite_formula import (
    MAX_FORMULA_DEPTH,
    MAX_FORMULA_NODES,
    CompositeFormula,
    CompositeFormulaError,
    FormulaValue,
)


class TestCompositeFormula(SimpleTestCase):
    @parameterized.expand(
        [
            (example["name"], example)
            for example in json.loads(
                (
                    Path(__file__).parents[2] / "frontend/scoreDefinitions/compositeFormulaDefaults.fixtures.json"
                ).read_text()
            )
            if example["expression"] is not None
        ]
    )
    def test_frontend_default_formulas_parse(self, _name: str, example: dict[str, Any]) -> None:
        inputs = {f"s{index}": example["inputKind"] for index in range(example["count"])}
        formula = CompositeFormula.parse(example["expression"], inputs, example["kind"])
        values: dict[str, FormulaValue] = {"boolean": True, "numeric": 0.7, "categorical": ["good"]}
        value = values[example["inputKind"]]
        expected = True if example["kind"] == "boolean" else 0.7 if example["inputKind"] == "numeric" else 1.0
        self.assertEqual(formula.evaluate(dict.fromkeys(inputs, value)), expected)

    @parameterized.expand(
        [
            ("(2 * p + r) / 3", {"p": "numeric", "r": "numeric"}, "numeric", {"p": 0.9, "r": 0.6}, 0.8),
            ("(number(a) + number(b)) / 2", {"a": "boolean", "b": "boolean"}, "numeric", {"a": True, "b": False}, 0.5),
            ('number("good" in label)', {"label": "categorical"}, "numeric", {"label": ["good"]}, 1.0),
            (
                '"good" if a and b else "bad"',
                {"a": "boolean", "b": "boolean"},
                "categorical",
                {"a": True, "b": False},
                "bad",
            ),
            ("a and b", {"a": "boolean", "b": "boolean"}, "boolean", {"a": True, "b": False}, False),
            ("1 / x if x > 0 else 0", {"x": "numeric"}, "numeric", {"x": 0.0}, 0.0),
            ("max(abs(x), 2)", {"x": "numeric"}, "numeric", {"x": -4.0}, 4.0),
            ("a or b", {"a": "boolean", "b": "boolean"}, "boolean", {"a": True, "b": False}, True),
            ("not a", {"a": "boolean"}, "boolean", {"a": False}, True),
            ("x - 0.3", {"x": "numeric"}, "numeric", {"x": 1.0}, 0.7),
            ("-x", {"x": "numeric"}, "numeric", {"x": 2.0}, -2.0),
            ("+x", {"x": "numeric"}, "numeric", {"x": 2.0}, 2.0),
            ("min(x, 2)", {"x": "numeric"}, "numeric", {"x": 4.0}, 2.0),
            ("x <= 0.7", {"x": "numeric"}, "boolean", {"x": 0.7}, True),
            ("x != 0", {"x": "numeric"}, "boolean", {"x": 1.0}, True),
            ('"good" not in label', {"label": "categorical"}, "boolean", {"label": ["bad"]}, True),
            (
                "(a + b + c) / 3",
                dict.fromkeys(["a", "b", "c"], "numeric"),
                "numeric",
                dict.fromkeys(["a", "b", "c"], 0.7),
                0.7,
            ),
            (
                "(a + b + c) / 3 >= 0.7",
                dict.fromkeys(["a", "b", "c"], "numeric"),
                "boolean",
                dict.fromkeys(["a", "b", "c"], 0.7),
                True,
            ),
            ("a\nand b", {"a": "boolean", "b": "boolean"}, "boolean", {"a": True, "b": True}, True),
            ('"good"\nif a\nelse "bad"', {"a": "boolean"}, "categorical", {"a": True}, "good"),
        ]
    )
    def test_typed_combinations(
        self, expression: str, types: dict[str, str], kind: str, values: dict[str, FormulaValue], expected: FormulaValue
    ) -> None:
        result = CompositeFormula.parse(expression, types, kind).evaluate(values)
        self.assertEqual(result, expected)

    @parameterized.expand(
        [
            ("__import__('os').system('id')",),
            ("x.__class__",),
            ("[x for x in [1]]",),
            ("x ** 1000000",),
            ("x[0]",),
            ("x + True",),
            ("x and True",),
            ("1e999 + x",),
            ("x + missing",),
            ("max(x, key=x)",),
            ("'a' * x",),
            ("+" * 30 + "x",),
            ("x+" * 200 + "x",),
            ("(x," * 200,),
            ("(x," * 199,),
        ]
    )
    def test_rejects_unsafe_or_ill_typed_formulas(self, expression: str) -> None:
        with self.assertRaises(CompositeFormulaError):
            CompositeFormula.parse(expression, {"x": "numeric"}, "numeric")

    @parameterized.expand([("x / 0",), ("x * 1e308",)])
    def test_runtime_arithmetic_errors_are_controlled(self, expression: str) -> None:
        formula = CompositeFormula.parse(expression, {"x": "numeric"}, "numeric")
        with self.assertRaises(CompositeFormulaError):
            formula.evaluate({"x": 100.0})

    def test_requires_all_declared_inputs_and_correct_output_type(self) -> None:
        for inputs, output in [({"x": "numeric", "y": "numeric"}, "numeric"), ({"x": "numeric"}, "boolean")]:
            with self.assertRaises(CompositeFormulaError):
                CompositeFormula.parse("x", inputs, output)

    def test_nested_conditionals_have_bounded_validation_work(self) -> None:
        expression = "x"
        for _ in range(MAX_FORMULA_DEPTH):
            expression = f"({expression} if True else 0)"
        with patch.object(CompositeFormula, "_infer", autospec=True, side_effect=CompositeFormula._infer) as infer:
            formula = CompositeFormula.parse(expression, {"x": "numeric"}, "numeric")
        self.assertLessEqual(infer.call_count, MAX_FORMULA_NODES)
        self.assertEqual(formula.evaluate({"x": 3.0}), 3.0)
