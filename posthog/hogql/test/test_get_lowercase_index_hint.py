from posthog.test.base import BaseTest

from posthog.schema import LogPropertyFilter, LogPropertyFilterType, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.property import _LowercaseIndexRewriter, get_lowercase_index_hint
from posthog.hogql.visitor import clear_locations


class TestGetLowercaseIndexHint(BaseTest):
    """Tests for get_lowercase_index_hint and _LowercaseIndexRewriter."""

    maxDiff = None

    def _hint(self, property) -> ast.Expr:
        return clear_locations(get_lowercase_index_hint(property, team=self.team))

    def _rewrite(self, expr: ast.Expr) -> ast.Expr:
        return clear_locations(_LowercaseIndexRewriter().visit(expr))

    def test_icontains_single_value_log_property(self):
        """ICONTAINS single value on a log property: toString stripped, ILike→Like, lower() wrapped, constant lowered."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS,
            value="ERROR",
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        # indexHint(lower(message) Like '%error%')
        assert isinstance(result, ast.Call)
        assert result.name == "indexHint"
        assert len(result.args) == 1

        inner = result.args[0]
        assert isinstance(inner, ast.CompareOperation)
        assert inner.op == ast.CompareOperationOp.Like

        # left: lower(message)
        assert isinstance(inner.left, ast.Call)
        assert inner.left.name == "lower"
        assert len(inner.left.args) == 1
        assert isinstance(inner.left.args[0], ast.Field)
        assert inner.left.args[0].chain == ["message"]

        # right: '%error%' (lowered)
        assert isinstance(inner.right, ast.Constant)
        assert inner.right.value == "%error%"

    def test_not_icontains_single_value_log_property(self):
        """NOT_ICONTAINS single value: NotILike→NotLike, lower() wrapped, constant lowered."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.NOT_ICONTAINS,
            value="DEBUG",
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        assert isinstance(result, ast.Call)
        assert result.name == "indexHint"

        inner = result.args[0]
        assert isinstance(inner, ast.CompareOperation)
        assert inner.op == ast.CompareOperationOp.NotLike

        assert isinstance(inner.left, ast.Call)
        assert inner.left.name == "lower"
        assert isinstance(inner.left.args[0], ast.Field)
        assert inner.left.args[0].chain == ["message"]

        assert isinstance(inner.right, ast.Constant)
        assert inner.right.value == "%debug%"

    def test_icontains_multi_value_log_property(self):
        """ICONTAINS with multiple values uses multiSearchAnyCaseInsensitive → multiSearchAny(lower(...), lowered)."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS,
            value=["ERROR", "WARNING"],
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        assert isinstance(result, ast.Call)
        assert result.name == "indexHint"

        # The inner expr should be: multiSearchAny(lower(message), ['error', 'warning']) > 0
        inner = result.args[0]
        assert isinstance(inner, ast.CompareOperation)
        assert inner.op == ast.CompareOperationOp.Gt

        search_call = inner.left
        assert isinstance(search_call, ast.Call)
        assert search_call.name == "multiSearchAny"
        assert len(search_call.args) == 2

        # haystack: lower(message)
        haystack = search_call.args[0]
        assert isinstance(haystack, ast.Call)
        assert haystack.name == "lower"
        assert isinstance(haystack.args[0], ast.Field)
        assert haystack.args[0].chain == ["message"]

        # needles: ['error', 'warning']
        needles = search_call.args[1]
        assert isinstance(needles, ast.Array)
        assert len(needles.exprs) == 2
        assert needles.exprs[0].value == "error"
        assert needles.exprs[1].value == "warning"

        # right side of >: 0
        assert isinstance(inner.right, ast.Constant)
        assert inner.right.value == 0

    def test_icontains_mixed_case_preserved_as_lower(self):
        """Mixed-case value is lowered in the hint."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS,
            value="FaTaL Error",
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        inner = result.args[0]
        assert inner.right.value == "%fatal error%"

    def test_icontains_multi_with_mixed_case_needles(self):
        """Multiple mixed-case needles are all lowered."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS,
            value=["FoO", "BaR", "BAZ"],
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        search_call = result.args[0].left
        needles = search_call.args[1]
        assert [e.value for e in needles.exprs] == ["foo", "bar", "baz"]

    def test_icontains_multi_operator_single_value(self):
        """ICONTAINS_MULTI with a single string value uses multiSearch path."""
        prop = LogPropertyFilter(
            key="message",
            operator=PropertyOperator.ICONTAINS_MULTI,
            value="Err",
            type=LogPropertyFilterType.LOG,
        )
        result = self._hint(prop)

        assert result.name == "indexHint"
        inner = result.args[0]
        assert isinstance(inner, ast.CompareOperation)
        assert inner.op == ast.CompareOperationOp.Gt

        search_call = inner.left
        assert isinstance(search_call, ast.Call)
        assert search_call.name == "multiSearchAny"
        needles = search_call.args[1]
        assert isinstance(needles, ast.Array)
        assert [e.value for e in needles.exprs] == ["err"]
