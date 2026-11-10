from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.composite_formula import CompositeFormula, CompositeFormulaError, FormulaValue


class TestCompositeFormula(SimpleTestCase):
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
        ]
    )
    def test_typed_combinations(
        self, expression: str, types: dict[str, str], kind: str, values: dict[str, FormulaValue], expected: FormulaValue
    ) -> None:
        result = CompositeFormula.parse(expression, types, kind).evaluate(values)
        if isinstance(expected, float):
            assert isinstance(result, float)
            self.assertAlmostEqual(result, expected)
        else:
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
