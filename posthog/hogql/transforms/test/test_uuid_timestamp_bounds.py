from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast

# Embeds 2026-07-20 12:00:00.000 UTC
UUID_LATE = "019f7f65-b600-7123-8abc-0123456789ab"
LATE_LOWER = "toDateTime64('2026-07-17 12:00:00.000000', 6, 'UTC')"
LATE_UPPER = "toDateTime64('2026-07-23 12:00:00.000000', 6, 'UTC')"

# Embeds 2026-06-25 18:17:07.840 UTC
UUID_EARLY = "019f0000-0000-7123-8abc-0123456789ab"
EARLY_LOWER = "toDateTime64('2026-06-22 18:17:07.840000', 6, 'UTC')"
EARLY_UPPER = "toDateTime64('2026-06-28 18:17:07.840000', 6, 'UTC')"

UUID_V4 = "a1b2c3d4-e5f6-4711-8899-aabbccddeeff"


class TestUuidTimestampBounds(BaseTest):
    def _print(self, select: str, dialect: HogQLDialect = "clickhouse") -> str:
        query, _ = prepare_and_print_ast(
            parse_select(select),
            HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=HogQLQueryModifiers()),
            dialect,
        )
        return query

    @parameterized.expand(
        [
            ("eq", f"SELECT event FROM events WHERE uuid = '{UUID_LATE}'", LATE_LOWER, LATE_UPPER, "events"),
            ("eq_flipped", f"SELECT event FROM events WHERE '{UUID_LATE}' = uuid", LATE_LOWER, LATE_UPPER, "events"),
            (
                "eq_touuid",
                f"SELECT event FROM events WHERE uuid = toUUID('{UUID_LATE}')",
                LATE_LOWER,
                LATE_UPPER,
                "events",
            ),
            (
                "in_list_spans_min_to_max",
                f"SELECT event FROM events WHERE uuid IN ('{UUID_LATE}', '{UUID_EARLY}')",
                EARLY_LOWER,
                LATE_UPPER,
                "events",
            ),
            (
                "and_with_other_filter",
                f"SELECT event FROM events WHERE uuid = '{UUID_LATE}' AND event = 'x'",
                LATE_LOWER,
                LATE_UPPER,
                "events",
            ),
            (
                "or_with_both_branches_bounded",
                f"SELECT event FROM events WHERE uuid = '{UUID_LATE}' OR uuid = '{UUID_EARLY}'",
                EARLY_LOWER,
                LATE_UPPER,
                "events",
            ),
            (
                "aliased_scan",
                f"SELECT event FROM events e WHERE e.uuid = '{UUID_LATE}'",
                LATE_LOWER,
                LATE_UPPER,
                "e",
            ),
        ]
    )
    def test_bounds_injected(self, _name: str, select: str, lower: str, upper: str, table: str) -> None:
        printed = self._print(select)
        assert f"greaterOrEquals({table}.timestamp, {lower})" in printed
        assert f"lessOrEquals({table}.timestamp, {upper})" in printed

    @parameterized.expand(
        [
            ("uuid_v4", f"SELECT event FROM events WHERE uuid = '{UUID_V4}'"),
            ("nil_uuid", "SELECT event FROM events WHERE uuid = '00000000-0000-0000-0000-000000000000'"),
            (
                "v7_beyond_datetime_range",
                "SELECT event FROM events WHERE uuid = 'ffffffff-ffff-7fff-8fff-ffffffffffff'",
            ),
            (
                "v7_near_datetime_max",
                "SELECT event FROM events WHERE uuid = 'e677c7d3-2400-7abc-8abc-0123456789ab'",
            ),
            ("non_constant", "SELECT event FROM events WHERE uuid = toUUID(event)"),
            (
                "or_with_unbounded_branch",
                f"SELECT event FROM events WHERE uuid = '{UUID_LATE}' OR event = 'x'",
            ),
            ("negated", f"SELECT event FROM events WHERE NOT (uuid = '{UUID_LATE}')"),
            ("not_in", f"SELECT event FROM events WHERE uuid NOT IN ('{UUID_LATE}')"),
            (
                "in_subquery",
                f"SELECT event FROM events WHERE uuid IN (SELECT uuid FROM events WHERE event = 'x')",
            ),
            (
                "in_list_with_non_v7_element",
                f"SELECT event FROM events WHERE uuid IN ('{UUID_LATE}', '{UUID_V4}')",
            ),
        ]
    )
    def test_no_bounds_injected(self, _name: str, select: str) -> None:
        printed = self._print(select)
        assert "greaterOrEquals" not in printed
        assert "lessOrEquals" not in printed

    def test_bound_applies_to_the_select_owning_the_lookup(self) -> None:
        printed = self._print(
            f"SELECT event FROM (SELECT event, timestamp FROM events WHERE uuid = '{UUID_LATE}') WHERE timestamp > '2020-01-01'"
        )
        assert printed.count(f"greaterOrEquals(events.timestamp, {LATE_LOWER})") == 1

    def test_hogql_dialect_is_not_rewritten(self) -> None:
        printed = self._print(f"SELECT event FROM events WHERE uuid = '{UUID_LATE}'", dialect="hogql")
        assert "greaterOrEquals" not in printed
        assert "timestamp" not in printed
