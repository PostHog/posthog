from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.schema import GroupPropertyFilter, PropertyOperator

from posthog.hogql import ast

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.session_recordings.queries.sub_queries.group_key_resolver import (
    MAX_RESOLVED_GROUP_KEYS,
    _resolution_predicate,
    resolved_group_key_expr,
)

_RESOLVER = "posthog.session_recordings.queries.sub_queries.group_key_resolver._query_group_keys"
_CH_USER = ClickHouseUser.DEFAULT


def _filter(operator: PropertyOperator = PropertyOperator.EXACT) -> GroupPropertyFilter:
    return GroupPropertyFilter(key="owner", value=["a@example.com"], operator=operator, group_type_index=0)


class TestGroupKeyResolver(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_a_resolvable_filter_becomes_an_in_over_the_group_column(self) -> None:
        with patch(_RESOLVER, return_value=["org-1", "org-2"]):
            expr = resolved_group_key_expr(self.team, _filter(), _CH_USER)

        assert isinstance(expr, ast.CompareOperation)
        assert expr.op == ast.CompareOperationOp.In
        assert isinstance(expr.left, ast.Field)
        assert expr.left.chain == ["events", "$group_0"]
        assert isinstance(expr.right, ast.Constant)
        assert expr.right.value == ["org-1", "org-2"]

    def test_the_second_build_reuses_the_first_resolution(self) -> None:
        # Without the cache every sweep tick re-scans the whole groups table, which is the cost this
        # resolution exists to remove.
        with patch(_RESOLVER, return_value=["org-1"]) as resolve:
            resolved_group_key_expr(self.team, _filter(), _CH_USER)
            resolved_group_key_expr(self.team, _filter(), _CH_USER)

        assert resolve.call_count == 1

    def test_a_different_team_does_not_read_another_teams_keys(self) -> None:
        other = self.organization.teams.create(name="other")
        with patch(_RESOLVER, return_value=["org-1"]) as resolve:
            resolved_group_key_expr(self.team, _filter(), _CH_USER)
            resolved_group_key_expr(other, _filter(), _CH_USER)

        assert resolve.call_count == 2

    @parameterized.expand(
        [
            # An IN list over matching keys cannot say "has a group, and it does not match", so a
            # negated filter resolved this way would silently change which sessions match.
            ("negated", PropertyOperator.IS_NOT),
            ("not_contains", PropertyOperator.NOT_ICONTAINS),
        ]
    )
    def test_an_operator_the_key_list_cannot_express_keeps_the_join(
        self, _name: str, operator: PropertyOperator
    ) -> None:
        with patch(_RESOLVER, return_value=["org-1"]):
            assert resolved_group_key_expr(self.team, _filter(operator), _CH_USER) is None

    def test_an_over_broad_filter_keeps_the_join(self) -> None:
        keys = [f"org-{i}" for i in range(MAX_RESOLVED_GROUP_KEYS + 1)]
        with patch(_RESOLVER, return_value=keys) as resolve:
            assert resolved_group_key_expr(self.team, _filter(), _CH_USER) is None
            assert resolved_group_key_expr(self.team, _filter(), _CH_USER) is None

        assert resolve.call_count == 1

    def test_a_numeric_comparison_casts_the_property(self) -> None:
        # Without the cast ClickHouse rejects the resolution with "no supertype for types String,
        # Float64", the resolver falls back, and the scanner silently keeps paying for the join.
        prop = GroupPropertyFilter(key="score", value=8, operator=PropertyOperator.GT, group_type_index=0)

        predicate = _resolution_predicate(self.team, prop)

        assert isinstance(predicate, ast.CompareOperation)
        assert predicate.op == ast.CompareOperationOp.Gt
        assert isinstance(predicate.left, ast.Call)
        assert predicate.left.name == "toFloat"
        assert isinstance(predicate.right, ast.Constant)
        assert predicate.right.value == 8.0

    @parameterized.expand([("read", "get"), ("write", "set")])
    def test_a_broken_cache_does_not_fail_the_query(self, _name: str, method: str) -> None:
        # Everything here is an optimisation over a join that already works, so an unavailable Redis
        # has to cost reads rather than break the sweep tick that was building the query.
        with patch(
            f"posthog.session_recordings.queries.sub_queries.group_key_resolver.cache.{method}",
            side_effect=Exception("redis is down"),
        ):
            with patch(_RESOLVER, return_value=["org-1"]):
                expr = resolved_group_key_expr(self.team, _filter(), _CH_USER)

        # A broken cache degrades to resolving every time, not to failing and not to the join.
        assert isinstance(expr, ast.CompareOperation)

    def test_a_failed_resolution_keeps_the_join(self) -> None:
        with patch(_RESOLVER, side_effect=Exception("clickhouse said no")):
            assert resolved_group_key_expr(self.team, _filter(), _CH_USER) is None
