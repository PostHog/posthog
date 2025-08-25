from posthog.test.base import APIBaseTest

from posthog.hogql_queries.utils.formula_ast import FormulaAST


class TestFormulaAST(APIBaseTest):
    def _get_formula_ast(self) -> FormulaAST:
        formula = FormulaAST(data=[[1, 2, 3, 4], [1, 2, 3, 4]])
        return formula

    def test_addition(self):
        formula = self._get_formula_ast()
        response = formula.call("A+1")
        self.assertListEqual([2, 3, 4, 5], response)

    def test_subtraction(self):
        formula = self._get_formula_ast()
        response = formula.call("A-1")
        self.assertListEqual([0, 1, 2, 3], response)

    def test_multiplication(self):
        formula = self._get_formula_ast()
        response = formula.call("A*2")
        self.assertListEqual([2, 4, 6, 8], response)

    def test_division(self):
        formula = self._get_formula_ast()
        response = formula.call("A/2")
        self.assertListEqual([0.5, 1, 1.5, 2], response)

    def test_division_zero(self):
        formula = self._get_formula_ast()
        response = formula.call("A/0")
        self.assertListEqual([0, 0, 0, 0], response)

    def test_modulo(self):
        formula = self._get_formula_ast()
        response = formula.call("A%2")
        self.assertListEqual([1, 0, 1, 0], response)

    def test_power(self):
        formula = self._get_formula_ast()
        response = formula.call("A**2")
        self.assertListEqual([1, 4, 9, 16], response)

    def test_constants(self):
        formula = self._get_formula_ast()
        response = formula.call("1")
        self.assertListEqual([1, 1, 1, 1], response)

    def test_named_values(self):
        formula = self._get_formula_ast()
        response = formula.call("A+B")
        self.assertListEqual([2, 4, 6, 8], response)

    def test_named_values_lower_case(self):
        formula = self._get_formula_ast()
        response = formula.call("a+b")
        self.assertListEqual([2, 4, 6, 8], response)

    def test_unary_minus(self):
        formula = self._get_formula_ast()
        response = formula.call("-A")
        self.assertListEqual([-1, -2, -3, -4], response)

    def test_unary_plus(self):
        formula = self._get_formula_ast()
        response = formula.call("+A")
        self.assertListEqual([1, 2, 3, 4], response)
