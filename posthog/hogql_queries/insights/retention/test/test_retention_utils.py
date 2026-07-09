from typing import cast

from django.test import SimpleTestCase

from posthog.hogql import ast

from posthog.hogql_queries.insights.retention.utils import breakdown_extract_expr


def _chain(expr: ast.Expr) -> list:
    # breakdown_extract_expr wraps the field in ifNull(toString(<field>), '')
    to_string = cast(ast.Call, cast(ast.Call, expr).args[0])
    return cast(ast.Field, to_string.args[0]).chain


class TestBreakdownExtractExpr(SimpleTestCase):
    def test_group_breakdown_uses_events_lazy_join_chain(self) -> None:
        # Group properties are read via the events table lazy join `group_{index}`,
        # not a standalone `groups_{index}` table.
        expr = breakdown_extract_expr("industry", "group", group_type_index=0)
        self.assertEqual(_chain(expr), ["group_0", "properties", "industry"])

    def test_group_breakdown_coerces_float_index(self) -> None:
        expr = breakdown_extract_expr("industry", "group", group_type_index=cast(int, 1.0))
        self.assertEqual(_chain(expr), ["group_1", "properties", "industry"])

    def test_group_breakdown_without_index_raises_clear_error(self) -> None:
        # A missing index must fail loudly rather than emit an unresolvable `group_None` field.
        with self.assertRaises(ValueError):
            breakdown_extract_expr("industry", "group", group_type_index=None)
