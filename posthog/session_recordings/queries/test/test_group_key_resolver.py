from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.schema import GroupPropertyFilter, HogQLPropertyFilter, PropertyOperator

from posthog.hogql import ast

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.models import User
from posthog.session_recordings.queries.sub_queries.group_key_resolver import (
    MAX_GROUP_KEY_LOOKUPS,
    MAX_RESOLVED_GROUP_KEYS,
    GroupKeyLookupBudget,
    _resolution_predicate,
    resolved_group_key_expr,
    resolved_hogql_group_key_expr,
)

_RESOLVER = "posthog.session_recordings.queries.sub_queries.group_key_resolver._query_group_keys"
_CH_USER = ClickHouseUser.DEFAULT


def _filter(
    operator: PropertyOperator = PropertyOperator.EXACT, value: Any = ("a@example.com",), key: str = "owner"
) -> GroupPropertyFilter:
    return GroupPropertyFilter(
        key=key, value=list(value) if isinstance(value, tuple) else value, operator=operator, group_type_index=0
    )


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
            # A half-filled filter matches every event through the join, groupless ones included.
            ("empty_list_value", PropertyOperator.ICONTAINS, []),
            ("no_value", PropertyOperator.EXACT, None),
            ("is_set_empty_list", PropertyOperator.IS_SET, []),
            # The lookup would read the key from the property JSON, find nothing, and match no session.
            ("group_key", PropertyOperator.EXACT, ("acme",), "$group_key"),
        ]
    )
    def test_an_operator_the_key_list_cannot_express_keeps_the_join(
        self, _name: str, operator: PropertyOperator, value: Any = ("a@example.com",), key: str = "owner"
    ) -> None:
        with patch(_RESOLVER, return_value=["org-1"]):
            assert resolved_group_key_expr(self.team, _filter(operator, value, key), _CH_USER) is None

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
        with patch(_RESOLVER, side_effect=Exception("clickhouse said no")) as resolve:
            assert resolved_group_key_expr(self.team, _filter(), _CH_USER) is None
            # Remembered, so a slow groups table is not queried again on the next listing.
            assert resolved_group_key_expr(self.team, _filter(), _CH_USER) is None
        assert resolve.call_count == 1

    def test_one_listings_lookups_share_a_budget(self) -> None:
        budget = GroupKeyLookupBudget()
        filters = [
            GroupPropertyFilter(key=f"key_{index}", value=["a"], operator=PropertyOperator.EXACT, group_type_index=0)
            for index in range(MAX_GROUP_KEY_LOOKUPS + 1)
        ]
        with patch(_RESOLVER, return_value=["org-1"]) as resolve:
            exprs = [resolved_group_key_expr(self.team, prop, _CH_USER, budget=budget) for prop in filters]
            # The filter left without budget is not remembered as a failure, so a fresh listing resolves it.
            assert resolved_group_key_expr(self.team, filters[-1], _CH_USER) is not None

        assert [expr is not None for expr in exprs] == [True] * MAX_GROUP_KEY_LOOKUPS + [False]
        assert resolve.call_count == MAX_GROUP_KEY_LOOKUPS + 1

    def test_keys_resolve_as_the_requesting_user_and_are_cached_per_user(self) -> None:
        other = User.objects.create(email="other@example.com")
        with patch(_RESOLVER, return_value=["org-1"]) as resolve:
            resolved_group_key_expr(self.team, _filter(), _CH_USER, self.user)
            resolved_group_key_expr(self.team, _filter(), _CH_USER, other)
            resolved_group_key_expr(self.team, _filter(), _CH_USER, self.user)
        # The lookup applies each user's property restrictions, so one user's keys never answer another's listing.
        assert [call.args[4] for call in resolve.call_args_list] == [self.user, other]

    @parameterized.expand(
        [
            ("one_group_type", "group_0.properties.is_owned = true OR toFloat(group_0.properties.mrr) > 1666", 0),
            ("other_group_type", "group_2.properties.plan = 'pro'", 2),
            # Each of these can also be true for an event with no group, which a key list would drop.
            ("negated", "NOT group_0.properties.plan = 'pro'", None),
            ("not_equal", "group_0.properties.plan != 'pro'", None),
            ("null_check", "group_0.properties.plan = null", None),
            ("coalesce", "coalesce(group_0.properties.plan, 'x') = 'x'", None),
            ("or_tautology", "group_0.properties.plan = 'pro' OR 1 = 1", None),
            ("or_constant_in", "group_0.properties.plan = 'pro' OR 'a' IN ('a')", None),
            ("two_properties_compared", "group_0.properties.a = group_0.properties.b", None),
            ("nested_comparison", "(group_0.properties.plan = 'pro') = false", None),
            ("null_producing_call", "toInt(group_0.properties.mrr) = toInt('invalid')", None),
            ("tuple_projection", "(group_0.properties.plan, 'pro').2 = 'pro'", None),
            # Anything outside one group type's properties needs the event row, so it keeps the join.
            ("mixes_event_properties", "group_0.properties.plan = 'pro' AND properties.$browser = 'Chrome'", None),
            ("two_group_types", "group_0.properties.plan = 'pro' OR group_1.properties.plan = 'pro'", None),
            ("event_property_only", "properties.$pathname ILIKE '%billing%'", None),
        ]
    )
    def test_a_hogql_filter_resolves_only_when_a_key_list_returns_the_same_sessions(
        self, _name: str, expression: str, expected_group_type: int | None
    ) -> None:
        with patch(_RESOLVER, return_value=["org-1"]) as resolve:
            expr = resolved_hogql_group_key_expr(self.team, HogQLPropertyFilter(key=expression), _CH_USER)

        if expected_group_type is None:
            assert expr is None
            resolve.assert_not_called()
            return
        assert isinstance(expr, ast.CompareOperation) and isinstance(expr.left, ast.Field)
        assert expr.left.chain == ["events", f"$group_{expected_group_type}"]
        # The predicate runs in a select over `groups`, where the property is read without the `group_N.` prefix.
        _team, group_type_index, predicate, _ch_user, _user, _seconds = resolve.call_args.args
        assert group_type_index == expected_group_type
        assert "group_" not in str(predicate)
