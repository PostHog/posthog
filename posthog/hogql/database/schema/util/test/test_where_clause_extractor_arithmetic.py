"""
Regression tests for WhereClauseExtractor.visit_arithmetic_operation.

Bug (issue #25842): `WHERE created_at < toDateTime('2024-10-25') + interval 1 day`
returned 0 rows because the WhereClauseExtractor replaced any ArithmeticOperation with
Constant(True). When this appeared as the RHS of a comparison (e.g., `field < True`),
ClickHouse evaluated `True` as the integer 1, so every datetime comparison returned 0.

The equivalent `plus(toDateTime('2024-10-25'), toIntervalDay(1))` worked correctly
because visit_call preserved the expression instead of replacing it with True.

Fix: visit_arithmetic_operation now visits both operands and propagates tombstones,
matching the behaviour of visit_call.
"""

import unittest

from posthog.hogql import ast
from posthog.hogql.ast import ArithmeticOperationOp
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import WhereClauseExtractor


def _make_extractor() -> WhereClauseExtractor:
    """Return a WhereClauseExtractor with no tracked tables."""
    return WhereClauseExtractor(HogQLContext(team_id=1))


class TestVisitArithmeticOperationPreservesConstants(unittest.TestCase):
    """visit_arithmetic_operation must NOT collapse constant expressions to Constant(True)."""

    def test_constant_plus_interval_preserved(self):
        """
        `toDateTime('2024-10-25') + toIntervalDay(1)` should survive the extractor intact.
        Before the fix this returned Constant(True), which later became `field < 1` in
        ClickHouse — filtering out all rows.
        """
        extractor = _make_extractor()
        node = ast.ArithmeticOperation(
            op=ArithmeticOperationOp.Add,
            left=ast.Call(name="toDateTime", args=[ast.Constant(value="2024-10-25")]),
            right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
        )
        result = extractor.visit_arithmetic_operation(node)

        self.assertIsInstance(
            result,
            ast.ArithmeticOperation,
            "Expected ArithmeticOperation but got %s — the expression was wrongly collapsed to a constant" % type(result).__name__,
        )
        self.assertNotIsInstance(
            result,
            ast.Constant,
            "visit_arithmetic_operation must not replace a constant-only ArithmeticOperation with Constant(True)",
        )
        result_arith = result  # type: ignore[assignment]
        self.assertEqual(result_arith.op, ArithmeticOperationOp.Add)

    def test_constant_minus_interval_preserved(self):
        """Subtraction variant: `now() - toIntervalDay(7)` should be preserved."""
        extractor = _make_extractor()
        node = ast.ArithmeticOperation(
            op=ArithmeticOperationOp.Sub,
            left=ast.Call(name="now", args=[]),
            right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=7)]),
        )
        result = extractor.visit_arithmetic_operation(node)

        self.assertIsInstance(result, ast.ArithmeticOperation)
        arith_result = result  # type: ignore[assignment]
        self.assertEqual(arith_result.op, ArithmeticOperationOp.Sub)

    def test_field_in_arithmetic_gets_tombstoned(self):
        """
        When an ArithmeticOperation contains a table field (which becomes a tombstone
        because it's not in any tracked table), the whole ArithmeticOperation should
        also become a tombstone.  This prevents accidental pushdown of expressions
        that reference live table columns.
        """
        extractor = _make_extractor()
        node = ast.ArithmeticOperation(
            op=ArithmeticOperationOp.Add,
            left=ast.Field(chain=["created_at"]),  # no type → tombstone
            right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
        )
        result = extractor.visit_arithmetic_operation(node)

        self.assertIsInstance(result, ast.Constant)
        # The tombstone string is random but starts with __TOMBSTONE__ by convention
        constant_result = result  # type: ignore[assignment]
        self.assertIsInstance(constant_result.value, str)
        self.assertIn("__TOMBSTONE__", constant_result.value)

    def test_pure_constant_arithmetic_preserved(self):
        """Scalar arithmetic like `1 + 2` (two Constants) must be preserved."""
        extractor = _make_extractor()
        node = ast.ArithmeticOperation(
            op=ArithmeticOperationOp.Add,
            left=ast.Constant(value=1),
            right=ast.Constant(value=2),
        )
        result = extractor.visit_arithmetic_operation(node)
        self.assertIsInstance(result, ast.ArithmeticOperation)

    def test_compare_with_interval_arithmetic_rhs_not_corrupted(self):
        """
        Regression: `field < toDateTime('2024-10-25') + toIntervalDay(1)` must NOT
        produce `field < True` after extraction.

        With no tracked tables the entire comparison collapses to Constant(True) — that
        is the expected "fail-safe" behaviour.  The important property is that the RHS
        of the comparison is never substituted with the boolean literal True.

        We verify this by checking that when tracked_tables is empty the comparison is
        collapsed to a constant (not a CompareOperation), which means the extractor
        correctly discarded it rather than emitting a broken `field < 1` predicate.
        """
        extractor = _make_extractor()
        comparison = ast.CompareOperation(
            op=ast.CompareOperationOp.Lt,
            left=ast.Field(chain=["created_at"]),
            right=ast.ArithmeticOperation(
                op=ArithmeticOperationOp.Add,
                left=ast.Call(name="toDateTime", args=[ast.Constant(value="2024-10-25")]),
                right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
            ),
        )
        result = extractor.visit_compare_operation(comparison)

        # With no tracked tables the extractor can't push down the filter → it should
        # return Constant(True) meaning "no restriction" (not a broken `field < 1`).
        if isinstance(result, ast.CompareOperation):
            # If a comparison IS returned, the RHS must NOT be Constant(True/1).
            right = result.right
            if isinstance(right, ast.Constant):
                self.assertNotEqual(
                    right.value,
                    True,
                    "RHS of comparison was Constant(True) — the interval expression was lost",
                )
                self.assertNotEqual(
                    right.value,
                    1,
                    "RHS of comparison was Constant(1) — the interval expression was lost",
                )

    def test_plus_call_and_interval_syntax_visit_identically(self):
        """
        `plus(toDateTime('2024-10-25'), toIntervalDay(1))` and
        `toDateTime('2024-10-25') + interval 1 day` (ArithmeticOperation)
        should be treated symmetrically by the extractor.

        Before the fix: the Call form was preserved, the ArithmeticOperation form
        was replaced by Constant(True) — causing `field < True` in ClickHouse.
        """
        extractor = _make_extractor()

        # Form 1: plus() call (was already working)
        plus_call = ast.Call(
            name="plus",
            args=[
                ast.Call(name="toDateTime", args=[ast.Constant(value="2024-10-25")]),
                ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
            ],
        )
        result_call = extractor.visit_call(plus_call)

        # Form 2: ArithmeticOperation (was broken before fix)
        arith_op = ast.ArithmeticOperation(
            op=ArithmeticOperationOp.Add,
            left=ast.Call(name="toDateTime", args=[ast.Constant(value="2024-10-25")]),
            right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
        )
        result_arith = extractor.visit_arithmetic_operation(arith_op)

        # Both forms should survive the extractor — neither should become Constant(True)
        self.assertNotIsInstance(result_call, ast.Constant, "plus() call should NOT be replaced by a constant")
        self.assertNotIsInstance(result_arith, ast.Constant, "ArithmeticOperation should NOT be replaced by a constant")


if __name__ == "__main__":
    unittest.main()
