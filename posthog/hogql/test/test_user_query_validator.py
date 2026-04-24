from typing import cast

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.user_query_validator import (
    HOGQL_PERSONAL_API_KEY_OFFSET_ALLOWED_FLAG,
    OFFSET_NOT_ALLOWED_MESSAGE,
    _OffsetDetectingVisitor,
    validate_user_query,
)


def _parse(sql: str) -> ast.SelectQuery | ast.SelectSetQuery:
    return cast(ast.SelectQuery | ast.SelectSetQuery, parse_select(sql))


def _flag_resolver(enabled_flags: set[str]):
    def _resolver(flag_key, _distinct_id, **_kwargs):
        return flag_key in enabled_flags

    return _resolver


class TestOffsetDetectingVisitor(BaseTest):
    """AST-level tests. Each reject case exercises a distinct AST attribute or recursion path."""

    # Each case is (description, sql). The description explains which code path it exercises —
    # cases that only vary in "AST shape for the same attribute check" are deliberately not listed.
    @parameterized.expand(
        [
            # SelectQuery.offset attribute
            ("top_level", "SELECT * FROM events WHERE timestamp > now() - INTERVAL 1 DAY LIMIT 100 OFFSET 50"),
            # Spec: OFFSET 0 rejects too ("no offsets at all"), not just OFFSET > 0
            ("offset_zero", "SELECT event FROM events LIMIT 100 OFFSET 0"),
            # Recursion via JoinExpr → nested SelectQuery (covers subquery + joined-subquery together)
            ("subquery", "SELECT event FROM (SELECT event FROM events LIMIT 5000 OFFSET 100000) sub"),
            # Recursion via CTE
            ("cte", "WITH recent AS (SELECT event FROM events LIMIT 5000 OFFSET 10000) SELECT * FROM recent"),
            # Recursion via SelectSetQuery children (UNION branch)
            (
                "union_branch",
                "SELECT event FROM events LIMIT 10 UNION ALL SELECT event FROM events LIMIT 10 OFFSET 10",
            ),
            # SelectSetQuery.offset attribute (distinct from SelectQuery.offset)
            (
                "select_set_outer",
                "(SELECT event FROM events LIMIT 10) UNION ALL (SELECT event FROM events LIMIT 10) LIMIT 100 OFFSET 5",
            ),
            # LimitByExpr.offset_value attribute (third distinct offset attribute)
            ("limit_by", "SELECT event, timestamp FROM events LIMIT 5 BY event OFFSET 10"),
        ]
    )
    def test_rejects(self, _name: str, sql: str) -> None:
        with self.assertRaises(QueryError) as ctx:
            _OffsetDetectingVisitor().visit(_parse(sql))
        self.assertEqual(OFFSET_NOT_ALLOWED_MESSAGE, str(ctx.exception))

    @parameterized.expand(
        [
            # Negative control: visitor must not raise when there's no pagination OFFSET
            ("no_offset", "SELECT event FROM events LIMIT 100"),
            # Guard against a false positive on SampleExpr.offset_value — a fourth offset-shaped
            # attribute that means sample-partition selection, not pagination. Must not trigger.
            (
                "sample_offset",
                "SELECT event FROM events SAMPLE 1/10 OFFSET 1/10 WHERE timestamp > now() - INTERVAL 1 DAY",
            ),
        ]
    )
    def test_accepts(self, _name: str, sql: str) -> None:
        _OffsetDetectingVisitor().visit(_parse(sql))


class TestValidateUserQuery(APIBaseTest):
    """Org-level allow-list gate. Callers are assumed to have already gated on is_query_service."""

    def _validate(self, sql: str) -> None:
        validate_user_query(_parse(sql), team=self.team, user=self.user)

    def test_rejects_offset_by_default(self):
        # Default: no allow-list entry → reject.
        with patch("posthoganalytics.feature_enabled", side_effect=_flag_resolver(set())):
            with self.assertRaises(QueryError) as ctx:
                self._validate("SELECT * FROM events LIMIT 100 OFFSET 50")
            self.assertEqual(OFFSET_NOT_ALLOWED_MESSAGE, str(ctx.exception))

    def test_allows_offset_when_org_on_allow_list(self):
        # Org is grandfathered via the flag → no rejection, visitor is skipped.
        with patch(
            "posthoganalytics.feature_enabled",
            side_effect=_flag_resolver({HOGQL_PERSONAL_API_KEY_OFFSET_ALLOWED_FLAG}),
        ):
            self._validate("SELECT * FROM events LIMIT 100 OFFSET 50")

    def test_fails_open_when_flag_service_errors(self):
        # Flag-service outage must not start rejecting previously-valid traffic.
        with patch("posthoganalytics.feature_enabled", side_effect=RuntimeError("flag service down")):
            self._validate("SELECT * FROM events LIMIT 100 OFFSET 50")
