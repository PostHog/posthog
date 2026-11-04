from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import time_machine

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.flag_calls_from_flag_evaluations import (
    FLAG_EVALUATIONS_COMPLETE_DAYS,
    EventsScan,
    can_read_flag_evaluations,
    filter_conjuncts,
)

from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_TTL_DAYS

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
COVERAGE_START = NOW.replace(hour=0) - timedelta(days=FLAG_EVALUATIONS_COMPLETE_DAYS)
IN_COVERAGE = COVERAGE_START + timedelta(days=30)

FLAG_CALLED = "event = '$feature_flag_called'"
FLAG_KEY = "properties.$feature_flag = 'my-flag'"
BOUND = "timestamp >= now() - INTERVAL 7 DAY"
UNQUALIFIED = f"{FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}"
OR_OF_AND_BRANCHES = (
    "((properties.$feature_flag = 'a' AND distinct_id = 'x') OR (properties.$feature_flag = 'b' AND distinct_id = 'y'))"
)
OR_CALL_OF_AND_CALLS = (
    "or(and(properties.$feature_flag = 'a', distinct_id = 'x'), and(properties.$feature_flag = 'b', distinct_id = 'y'))"
)


def _text(instant: datetime) -> str:
    return instant.strftime("%Y-%m-%d %H:%M:%S")


def _date(instant: datetime) -> str:
    return instant.strftime("%Y-%m-%d")


def _last_days_bound(timezone: str, days: int) -> str:
    local_today = NOW.astimezone(ZoneInfo(timezone)).date()
    date_from = datetime.combine(local_today - timedelta(days=days), time.min)
    return f"toStartOfInterval(assumeNotNull(toDateTime('{_text(date_from)}')), toIntervalDay(1))"


def _where(*conjuncts: str) -> str:
    return f"SELECT count() FROM events WHERE {' AND '.join(conjuncts)}"


def _on_posthog_events(where: str, select: str = "count()") -> str:
    return f"SELECT {select} FROM posthog.events WHERE {where}"


POSTHOG_EVENTS_QUALIFIED = (
    "posthog.events.event = '$feature_flag_called' AND posthog.events.properties.$feature_flag = 'my-flag' "
    "AND posthog.events.timestamp >= now() - INTERVAL 7 DAY"
)


def _bounded_by(lower_bound: str) -> str:
    return _where(FLAG_CALLED, FLAG_KEY, f"timestamp >= {lower_bound}")


def _nested(template: str, depth: int) -> str:
    expr = "properties.since"
    for _ in range(depth):
        expr = template.format(expr)
    return expr


def _joined(where: str) -> str:
    return f"SELECT count() FROM events AS e JOIN persons AS p ON e.person_id = p.id WHERE {where}"


def _self_joined(where: str) -> str:
    return f"SELECT count() FROM events AS e JOIN events AS f ON e.uuid = f.uuid WHERE {where}"


def _beside(join: str) -> str:
    return f"SELECT count() FROM events AS e {join} WHERE {UNQUALIFIED}"


@time_machine.travel(NOW, tick=False)
class TestCanReadFlagEvaluations(SimpleTestCase):
    def _can_read(
        self,
        query: str,
        placeholders: dict[str, ast.Expr] | None = None,
        timezone: str = "UTC",
        *,
        only_in_flag_evaluations: bool = False,
    ) -> bool:
        select = parse_select(query, placeholders=placeholders)
        assert isinstance(select, ast.SelectQuery)
        return can_read_flag_evaluations(
            select, datetime.now(UTC), ZoneInfo(timezone), only_in_flag_evaluations=only_in_flag_evaluations
        )

    @parameterized.expand(
        [
            ("or_of_and_branches", _where(FLAG_CALLED, OR_OF_AND_BRANCHES)),
            ("or_call_of_and_calls", _where(FLAG_CALLED, OR_CALL_OF_AND_CALLS)),
        ]
    )
    def test_flag_keys_cover_every_branch_of_an_or(self, _name: str, query: str):
        select = parse_select(query)
        assert isinstance(select, ast.SelectQuery)
        scan = EventsScan.of(select, lambda: True, frozenset())
        assert scan is not None
        assert scan.flag_keys(filter_conjuncts(select)) == ["a", "b"]

    def test_complete_days_leave_out_the_day_the_ttl_may_have_dropped(self):
        assert FLAG_EVALUATIONS_COMPLETE_DAYS < FLAG_EVALUATIONS_TTL_DAYS

    @parameterized.expand(
        [
            ("event_equals", _where(FLAG_CALLED, FLAG_KEY, BOUND)),
            ("event_equals_call", _where("equals(event, '$feature_flag_called')", FLAG_KEY, BOUND)),
            ("event_in_one_value", _where("event IN ('$feature_flag_called')", FLAG_KEY, BOUND)),
            (
                "or_of_pinned_branches_with_their_own_flag_keys",
                _where(
                    "((event = '$feature_flag_called' AND properties.$feature_flag = 'a') "
                    "OR (event = '$feature_flag_called' AND properties.$feature_flag = 'b'))",
                    BOUND,
                ),
            ),
            ("or_of_flag_keys_with_other_conditions", _where(FLAG_CALLED, OR_OF_AND_BRANCHES, BOUND)),
            (
                "or_call_of_flag_keys",
                _where(FLAG_CALLED, "or(properties.$feature_flag = 'a', properties.$feature_flag = 'b')", BOUND),
            ),
            (
                "or_call_of_pinned_branches_with_their_own_flag_keys",
                _where(
                    "or(and(event = '$feature_flag_called', properties.$feature_flag = 'a'), "
                    "and(event = '$feature_flag_called', properties.$feature_flag = 'b'))",
                    BOUND,
                ),
            ),
            ("pin_in_prewhere", f"SELECT count() FROM events PREWHERE {FLAG_CALLED} WHERE {FLAG_KEY} AND {BOUND}"),
            ("conjuncts_in_nested_ands", _where(FLAG_CALLED, f"({FLAG_KEY} AND ({BOUND} AND distinct_id = 'd'))")),
            (
                "qualified_without_an_alias",
                _where(
                    "events.event = '$feature_flag_called'",
                    "events.properties.$feature_flag = 'my-flag'",
                    "events.timestamp >= now() - INTERVAL 7 DAY",
                ),
            ),
            (
                "qualified_by_the_alias",
                "SELECT count() FROM events AS e WHERE e.event = '$feature_flag_called' "
                "AND e.properties.$feature_flag = 'my-flag' AND e.timestamp >= now() - INTERVAL 7 DAY",
            ),
            (
                "unqualified_under_an_alias_without_a_join",
                f"SELECT count() FROM events AS e WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}",
            ),
            (
                "qualified_by_the_alias_with_a_join",
                _joined(
                    "e.event = '$feature_flag_called' AND e.properties.$feature_flag = 'my-flag' "
                    "AND e.timestamp >= now() - INTERVAL 7 DAY"
                ),
            ),
            (
                "unqualified_event_with_a_join",
                _joined(
                    f"{FLAG_CALLED} AND e.properties.$feature_flag = 'my-flag' AND e.timestamp >= now() - INTERVAL 7 DAY"
                ),
            ),
            (
                "unqualified_bound_with_a_join",
                _joined(f"e.event = '$feature_flag_called' AND e.properties.$feature_flag = 'my-flag' AND {BOUND}"),
            ),
            (
                "unqualified_event_beside_a_table_aliased_event",
                "SELECT count() FROM events AS e JOIN persons AS event ON e.person_id = event.id "
                "WHERE event = '$feature_flag_called' AND e.properties.$feature_flag = 'my-flag' "
                "AND e.timestamp >= now() - INTERVAL 7 DAY",
            ),
            (
                "unqualified_reads_beside_a_joined_subquery",
                _beside(
                    "INNER JOIN (SELECT person_id AS cohort_person_id, 1 AS value FROM raw_cohort_people) AS cohort_join "
                    "ON e.person_id = cohort_join.cohort_person_id"
                ),
            ),
            (
                "unqualified_reads_beside_a_joined_union",
                _beside(
                    "LEFT JOIN (SELECT person_id AS cohort_person_id, 1 AS matched FROM static_cohort_people "
                    "UNION ALL SELECT person_id AS cohort_person_id, 1 AS matched FROM raw_cohort_people) AS __in_cohort "
                    "ON __in_cohort.cohort_person_id = e.person_id"
                ),
            ),
            (
                "unqualified_reads_beside_a_joined_cte",
                "WITH actors AS (SELECT person_id AS actor_id, min(timestamp) AS t_0 FROM events GROUP BY actor_id) "
                + _beside("INNER JOIN actors ON e.person_id = actors.actor_id"),
            ),
            (
                "unqualified_reads_beside_an_array_join",
                f"SELECT n FROM events ARRAY JOIN [1, 2] AS n WHERE {UNQUALIFIED}",
            ),
            (
                "alias_that_reads_the_scan_beside_a_subquery_with_an_event_column",
                "SELECT e.event AS event, count() FROM events AS e "
                "JOIN (SELECT distinct_id, event FROM events) AS calls ON e.distinct_id = calls.distinct_id "
                f"WHERE {UNQUALIFIED} GROUP BY event",
            ),
            ("flag_key_array_access", _where(FLAG_CALLED, "properties['$feature_flag'] = 'my-flag'", BOUND)),
            (
                "flag_key_array_access_by_the_alias",
                "SELECT count() FROM events AS e WHERE e.event = '$feature_flag_called' "
                "AND e.properties['$feature_flag'] = 'my-flag' AND e.timestamp >= now() - INTERVAL 7 DAY",
            ),
            (
                "flag_key_json_extract",
                _where(FLAG_CALLED, "JSONExtractString(properties, '$feature_flag') = 'my-flag'", BOUND),
            ),
            ("flag_key_equals_call", _where(FLAG_CALLED, "equals(properties.$feature_flag, 'my-flag')", BOUND)),
            ("flag_key_in_list", _where(FLAG_CALLED, "properties.$feature_flag IN ('a', 'b')", BOUND)),
            (
                "flag_key_or",
                _where(FLAG_CALLED, "(properties.$feature_flag = 'a' OR properties.$feature_flag = 'b')", BOUND),
            ),
            ("bound_greater", _where(FLAG_CALLED, FLAG_KEY, "timestamp > now() - INTERVAL 7 DAY")),
            ("bound_flipped_less_or_equals", _where(FLAG_CALLED, FLAG_KEY, "now() - INTERVAL 7 DAY <= timestamp")),
            ("bound_flipped_less", _where(FLAG_CALLED, FLAG_KEY, "now() - INTERVAL 7 DAY < timestamp")),
            ("bound_between", _where(FLAG_CALLED, FLAG_KEY, "timestamp BETWEEN now() - INTERVAL 7 DAY AND now()")),
            (
                "bound_greater_or_equals_call",
                _where(FLAG_CALLED, FLAG_KEY, "greaterOrEquals(timestamp, now() - INTERVAL 7 DAY)"),
            ),
            ("bound_greater_call", _where(FLAG_CALLED, FLAG_KEY, "greater(timestamp, now() - INTERVAL 7 DAY)")),
            (
                "latest_of_several_bounds",
                _where(FLAG_CALLED, FLAG_KEY, "timestamp >= now() - INTERVAL 365 DAY", BOUND),
            ),
            ("now64", _bounded_by("now64() - INTERVAL 7 DAY")),
            ("today", _bounded_by("today() - INTERVAL 7 DAY")),
            ("interval_function", _bounded_by("now() - toIntervalDay(7)")),
            ("minus_call", _bounded_by("minus(now(), toIntervalDay(7))")),
            ("subtract_days", _bounded_by("subtractDays(now(), 7)")),
            ("weeks", _bounded_by("now() - INTERVAL 12 WEEK")),
            ("months", _bounded_by("now() - INTERVAL 2 MONTH")),
            ("hours", _bounded_by("now() - INTERVAL 2000 HOUR")),
            ("plus_interval", _bounded_by("now() + INTERVAL 1 DAY")),
            ("last_covered_day", _bounded_by(f"now() - INTERVAL {FLAG_EVALUATIONS_COMPLETE_DAYS} DAY")),
            ("assume_not_null", _bounded_by("assumeNotNull(now() - INTERVAL 7 DAY)")),
            ("start_of_day", _bounded_by("toStartOfDay(now() - INTERVAL 7 DAY)")),
            ("start_of_week_with_a_mode", _bounded_by("toStartOfWeek(now() - INTERVAL 7 DAY, 1)")),
            ("start_of_month", _bounded_by("toStartOfMonth(now() - INTERVAL 7 DAY)")),
            ("start_of_interval", _bounded_by("toStartOfInterval(now() - INTERVAL 7 DAY, INTERVAL 1 DAY)")),
            (
                "trends_date_from",
                _bounded_by(f"toStartOfInterval(assumeNotNull(toDateTime('{_text(IN_COVERAGE)}')), toIntervalDay(1))"),
            ),
            ("to_date_time", _bounded_by(f"toDateTime('{_text(IN_COVERAGE)}')")),
            ("to_date_time_with_a_timezone", _bounded_by(f"toDateTime('{_text(IN_COVERAGE)}', 'UTC')")),
            ("to_date_time64", _bounded_by(f"toDateTime64('{_text(IN_COVERAGE)}', 6)")),
            ("to_date_time64_with_a_timezone", _bounded_by(f"toDateTime64('{_text(IN_COVERAGE)}', 6, 'UTC')")),
            ("to_date", _bounded_by(f"toDate('{_date(IN_COVERAGE)}')")),
            ("date_string", _bounded_by(f"'{_date(IN_COVERAGE)}'")),
            ("date_time_string", _bounded_by(f"'{_text(IN_COVERAGE)}'")),
            (
                "first_covered_day_in_utc",
                _bounded_by(f"toDateTime('{_text(COVERAGE_START + timedelta(hours=2))}', 'UTC')"),
            ),
            # The printer drops SAMPLE 1. The trends query builders set it on every events read.
            ("sample_of_one", f"SELECT count() FROM events SAMPLE 1 WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}"),
            ("posthog_events", _on_posthog_events(f"{FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}")),
            ("posthog_events_qualified_without_an_alias", _on_posthog_events(POSTHOG_EVENTS_QUALIFIED)),
            (
                "posthog_events_as_one_quoted_name",
                f"SELECT count() FROM `posthog.events` WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}",
            ),
            (
                "posthog_events_qualified_by_its_scope_name",
                _on_posthog_events(POSTHOG_EVENTS_QUALIFIED.replace("posthog.events.", "posthog__events.")),
            ),
            (
                "posthog_events_qualified_by_one_quoted_name",
                _on_posthog_events(POSTHOG_EVENTS_QUALIFIED.replace("posthog.events.", "`posthog.events`.")),
            ),
            (
                "posthog_events_qualifier_with_a_join",
                "SELECT count() FROM posthog.events JOIN persons AS p ON posthog.events.person_id = p.id "
                f"WHERE {POSTHOG_EVENTS_QUALIFIED}",
            ),
            (
                "alias_that_renames_its_own_column",
                f"SELECT e.timestamp AS timestamp FROM events e WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}",
            ),
        ]
    )
    def test_accepts_a_flag_call_query_inside_coverage(self, _name: str, query: str):
        assert self._can_read(query) is True

    @parameterized.expand(
        [
            ("aware_datetime", ast.Constant(value=COVERAGE_START), True),
            ("date", ast.Constant(value=(COVERAGE_START + timedelta(days=1)).date()), True),
            ("aware_datetime_before_coverage", ast.Constant(value=COVERAGE_START - timedelta(seconds=1)), False),
        ]
    )
    def test_reads_a_placeholder_bound_against_coverage(self, _name: str, bound: ast.Expr, expected: bool):
        assert self._can_read(_bounded_by("{bound}"), {"bound": bound}) is expected

    @parameterized.expand(
        [
            ("no_event_pin", _where(FLAG_KEY, BOUND)),
            ("mixed_in", _where("event IN ('$feature_flag_called', '$pageview')", FLAG_KEY, BOUND)),
            (
                "or_with_an_unpinned_branch",
                _where(
                    "((event = '$feature_flag_called' AND properties.$feature_flag = 'a') "
                    "OR (event = '$pageview' AND properties.$feature_flag = 'a'))",
                    BOUND,
                ),
            ),
            ("or_with_a_branch_on_another_column", _where(f"({FLAG_CALLED} OR distinct_id = 'd')", FLAG_KEY, BOUND)),
            ("negated_pin", _where(f"NOT ({FLAG_CALLED})", FLAG_KEY, BOUND)),
            (
                "pin_only_in_a_subquery",
                _where(FLAG_KEY, BOUND, f"uuid IN (SELECT uuid FROM events WHERE {FLAG_CALLED})"),
            ),
            (
                "flag_key_under_a_cte_named_properties",
                "WITH properties AS (SELECT 'my-flag' AS `$feature_flag`) " + _where(FLAG_CALLED, FLAG_KEY, BOUND),
            ),
            (
                "flag_key_beside_a_table_named_properties",
                _beside("JOIN properties ON e.distinct_id = properties.distinct_id"),
            ),
            (
                "flag_key_beside_a_subquery_named_properties",
                _beside(
                    "JOIN (SELECT person_id AS id FROM raw_cohort_people) AS properties ON e.person_id = properties.id"
                ),
            ),
            (
                "array_join_alias_that_shadows_event",
                f"SELECT count() FROM events ARRAY JOIN ['$feature_flag_called'] AS event WHERE {UNQUALIFIED}",
            ),
            (
                "pin_on_a_joined_alias",
                _self_joined(
                    "f.event = '$feature_flag_called' AND e.properties.$feature_flag = 'my-flag' "
                    "AND e.timestamp >= now() - INTERVAL 7 DAY"
                ),
            ),
            ("no_bound", _where(FLAG_CALLED, FLAG_KEY)),
            ("upper_bound_only", _where(FLAG_CALLED, FLAG_KEY, "timestamp <= now()")),
            ("flipped_upper_bound", _where(FLAG_CALLED, FLAG_KEY, "now() - INTERVAL 7 DAY >= timestamp")),
            (
                "greater_or_equals_call_with_flipped_arguments",
                _where(FLAG_CALLED, FLAG_KEY, "greaterOrEquals(now() - INTERVAL 7 DAY, timestamp)"),
            ),
            ("not_between", _where(FLAG_CALLED, FLAG_KEY, "timestamp NOT BETWEEN now() - INTERVAL 7 DAY AND now()")),
            ("bound_inside_an_or", _where(FLAG_CALLED, FLAG_KEY, f"({BOUND} OR distinct_id = 'd')")),
            ("bound_on_another_column", _where(FLAG_CALLED, FLAG_KEY, "created_at >= now() - INTERVAL 7 DAY")),
            (
                "bound_on_a_joined_alias",
                _self_joined(
                    "e.event = '$feature_flag_called' AND e.properties.$feature_flag = 'my-flag' "
                    "AND f.timestamp >= now() - INTERVAL 7 DAY"
                ),
            ),
            ("one_day_past_coverage", _bounded_by(f"now() - INTERVAL {FLAG_EVALUATIONS_COMPLETE_DAYS + 1} DAY")),
            ("months_past_coverage", _bounded_by("now() - INTERVAL 3 MONTH")),
            (
                "absolute_date_before_coverage",
                _bounded_by(f"toDateTime('{_text(COVERAGE_START - timedelta(seconds=1))}', 'UTC')"),
            ),
            ("to_date_on_the_first_covered_day", _bounded_by(f"toDate('{_date(COVERAGE_START)}')")),
            (
                "string_with_an_offset_before_coverage",
                _bounded_by(f"toDateTime('{_text(COVERAGE_START + timedelta(hours=6))}+14:00')"),
            ),
            ("negative_interval_added", _bounded_by("now() + INTERVAL -100 DAY")),
            ("subtract_days_past_coverage", _bounded_by(f"subtractDays(now(), {FLAG_EVALUATIONS_COMPLETE_DAYS + 1})")),
            (
                "start_of_month_before_coverage",
                _bounded_by(f"toStartOfMonth(now() - INTERVAL {FLAG_EVALUATIONS_COMPLETE_DAYS - 1} DAY)"),
            ),
            ("start_of_year", _bounded_by("toStartOfYear(now())")),
            (
                "start_of_interval_before_coverage",
                _bounded_by(
                    f"toStartOfInterval(now() - INTERVAL {FLAG_EVALUATIONS_COMPLETE_DAYS - 1} DAY, INTERVAL 1 MONTH)"
                ),
            ),
            ("bound_read_from_a_field", _bounded_by("toDateTime(properties.since)")),
            ("bound_from_a_subquery", _bounded_by("(SELECT min(timestamp) FROM events)")),
            ("interval_read_from_a_field", _bounded_by("now() - toIntervalDay(properties.days)")),
            ("sample", f"SELECT count() FROM events SAMPLE 0.1 WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}"),
            ("sample_ratio", f"SELECT count() FROM events SAMPLE 1/10 WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}"),
            (
                "sample_of_one_with_an_offset",
                f"SELECT count() FROM events SAMPLE 1 OFFSET 1/2 WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}",
            ),
            (
                "sample_of_rows",
                f"SELECT count() FROM events SAMPLE 10000 WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}",
            ),
            ("no_flag_key_pin", _where(FLAG_CALLED, BOUND)),
            (
                "flag_key_in_list_with_an_empty_string",
                _where(FLAG_CALLED, "properties.$feature_flag IN ('my-flag', '')", BOUND),
            ),
            ("flag_key_empty_string", _where(FLAG_CALLED, "properties.$feature_flag = ''", BOUND)),
            ("flag_key_not_empty", _where(FLAG_CALLED, "properties.$feature_flag != ''", BOUND)),
            ("flag_key_number", _where(FLAG_CALLED, "properties.$feature_flag = 1", BOUND)),
            (
                "flag_key_or_with_an_empty_string",
                _where(FLAG_CALLED, "(properties.$feature_flag = 'my-flag' OR properties.$feature_flag = '')", BOUND),
            ),
            (
                "flag_key_or_with_a_branch_on_another_column",
                _where(FLAG_CALLED, "(properties.$feature_flag = 'my-flag' OR distinct_id = 'd')", BOUND),
            ),
            (
                "flag_key_on_person_properties",
                _where(FLAG_CALLED, "person.properties.$feature_flag = 'my-flag'", BOUND),
            ),
            ("pin_on_another_property", _where(FLAG_CALLED, "properties.$feature_flag_response = 'my-flag'", BOUND)),
            (
                "flag_key_on_a_joined_alias",
                _self_joined(
                    "e.event = '$feature_flag_called' AND f.properties.$feature_flag = 'my-flag' "
                    "AND e.timestamp >= now() - INTERVAL 7 DAY"
                ),
            ),
            (
                "or_pin_with_a_branch_without_its_flag_key",
                _where(
                    f"((event = '$feature_flag_called' AND properties.$feature_flag = 'a') OR {FLAG_CALLED})",
                    BOUND,
                ),
            ),
            (
                "bound_on_an_alias_that_shadows_timestamp",
                f"SELECT now() AS timestamp FROM events WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}",
            ),
            (
                "pin_on_an_alias_that_shadows_event",
                f"SELECT '$feature_flag_called' AS event FROM events WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}",
            ),
            ("select_star", f"SELECT * FROM events WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}"),
            ("qualified_select_star", f"SELECT e.* FROM events e WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}"),
            ("columns_expression", f"SELECT COLUMNS('^p') FROM events WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}"),
            ("final", f"SELECT count() FROM events FINAL WHERE {FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}"),
            ("flag_key_that_reads_as_a_number", _where(FLAG_CALLED, "properties.$feature_flag = '100'", BOUND)),
            ("flag_key_that_reads_as_a_boolean", _where(FLAG_CALLED, "properties.$feature_flag = 'true'", BOUND)),
            ("flag_key_that_reads_as_json_null", _where(FLAG_CALLED, "properties.$feature_flag = 'null'", BOUND)),
            (
                "flag_key_list_with_an_object",
                _where(FLAG_CALLED, "properties.$feature_flag IN ('my-flag', '{\"a\": 1}')", BOUND),
            ),
            (
                "column_aliases",
                "SELECT count() FROM events AS e (uuid, event, properties, timestamp, distinct_id, x) "
                "WHERE e.event = '$feature_flag_called' AND e.properties.$feature_flag = 'my-flag' "
                "AND e.timestamp >= now() - INTERVAL 7 DAY",
            ),
            (
                "bare_star_with_an_array_join",
                "SELECT * FROM events ARRAY JOIN [1] AS n WHERE events.event = '$feature_flag_called' "
                "AND events.properties.$feature_flag = 'my-flag' AND events.timestamp >= now() - INTERVAL 7 DAY",
            ),
            (
                "posthog_events_qualifier_that_a_select_alias_shadows",
                _on_posthog_events(POSTHOG_EVENTS_QUALIFIED, select="properties AS posthog"),
            ),
            (
                "posthog_events_quoted_qualifier_that_a_select_alias_shadows",
                _on_posthog_events(
                    POSTHOG_EVENTS_QUALIFIED.replace("posthog.events.", "`posthog.events`."),
                    select="properties AS `posthog.events`",
                ),
            ),
            (
                "posthog_events_qualifier_that_a_cte_shadows",
                f"WITH posthog AS (SELECT 1) {_on_posthog_events(POSTHOG_EVENTS_QUALIFIED)}",
            ),
            (
                "posthog_events_qualifier_that_a_join_alias_shadows",
                "SELECT count() FROM posthog.events JOIN persons AS posthog ON posthog.events.person_id = posthog.id "
                f"WHERE {POSTHOG_EVENTS_QUALIFIED}",
            ),
            (
                "posthog_events_qualifier_under_another_alias",
                f"SELECT count() FROM posthog.events AS e WHERE {POSTHOG_EVENTS_QUALIFIED}",
            ),
            (
                "posthog_events_read_from_a_cte_of_that_name",
                "WITH `posthog.events` AS (SELECT event, properties, timestamp FROM posthog.flag_evaluations) "
                + _on_posthog_events(f"{FLAG_CALLED} AND {FLAG_KEY} AND {BOUND}"),
            ),
            ("bound_near_year_one", _bounded_by("'0001-01-01'")),
            ("interval_past_datetime_range", _bounded_by("now() - INTERVAL 999999999 YEAR")),
            # Each level used to evaluate its value twice, so 40 levels took 2^40 steps.
            ("deeply_nested_start_of_day_of_a_column", _bounded_by(_nested("toStartOfDay({})", 40))),
            (
                "deeply_nested_day_interval_of_a_column",
                _bounded_by(_nested("toStartOfInterval({}, toIntervalDay(1))", 40)),
            ),
        ]
    )
    @pytest.mark.timeout(5, func_only=True)
    def test_refuses_a_query_that_breaks_a_condition(self, _name: str, query: str):
        assert self._can_read(query) is False

    @parameterized.expand(
        [
            ("no_lower_bound", _where(FLAG_CALLED, FLAG_KEY), True),
            ("bound_before_coverage", _bounded_by("now() - INTERVAL 180 DAY"), True),
            ("no_flag_key", _where(FLAG_CALLED, BOUND), True),
            ("no_event_pin", _where(FLAG_KEY, BOUND), False),
            ("mixed_in", _where("event IN ('$feature_flag_called', '$pageview')", FLAG_KEY, BOUND), False),
            ("sample", f"SELECT count() FROM events SAMPLE 0.1 WHERE {FLAG_CALLED} AND {FLAG_KEY}", False),
            ("select_star", f"SELECT * FROM events WHERE {FLAG_CALLED}", False),
        ]
    )
    def test_skips_coverage_and_flag_key_when_only_flag_evaluations_has_flag_calls(
        self, _name: str, query: str, expected: bool
    ):
        assert self._can_read(query, only_in_flag_evaluations=True) is expected

    @parameterized.expand(
        [
            # The trends runner's date range for "Last N days" in a day-interval insight.
            *[
                (f"last_{label}_days_in_{zone}", zone, _last_days_bound(zone, days), expected)
                for zone in ("UTC", "Pacific/Kiritimati", "Etc/GMT+12")
                for label, days, expected in (
                    ("complete", FLAG_EVALUATIONS_COMPLETE_DAYS - 1, True),
                    ("too_many", FLAG_EVALUATIONS_COMPLETE_DAYS + 1, False),
                )
            ],
            # Pacific/Kiritimati is UTC+14, so its midnight on the first covered day is 10:00 the day before in UTC.
            ("to_date_time_on_the_first_covered_day_in_utc", "UTC", f"toDateTime('{_text(COVERAGE_START)}')", True),
            (
                "to_date_time_on_the_first_covered_day_in_kiritimati",
                "Pacific/Kiritimati",
                f"toDateTime('{_text(COVERAGE_START)}')",
                False,
            ),
            ("date_string_on_the_first_covered_day_in_utc", "UTC", f"'{_date(COVERAGE_START)}'", True),
            (
                "date_string_on_the_first_covered_day_in_kiritimati",
                "Pacific/Kiritimati",
                f"'{_date(COVERAGE_START)}'",
                False,
            ),
            (
                "naive_placeholder_on_the_first_covered_day_in_kiritimati",
                "Pacific/Kiritimati",
                "{bound}",
                False,
            ),
            ("naive_placeholder_on_the_first_covered_day_in_utc", "UTC", "{bound}", True),
        ]
    )
    def test_reads_a_time_without_a_zone_in_the_team_timezone(
        self, _name: str, timezone: str, bound: str, expected: bool
    ):
        placeholders: dict[str, ast.Expr] = {"bound": ast.Constant(value=COVERAGE_START.replace(tzinfo=None))}

        assert self._can_read(_bounded_by(bound), placeholders, timezone) is expected

    @parameterized.expand(
        [
            (
                "date_rounding_shifted_in_a_zone_behind_utc",
                datetime(2026, 10, 24, 12, 0, tzinfo=UTC),
                "America/Los_Angeles",
                "toMonday(toDateTime('2026-08-02 22:00:00')) - INTERVAL 1 HOUR",
            ),
            # Troll is on UTC+0 now and was on UTC+2 89 days back, so subtracting 89 days lands two hours earlier
            # in UTC than 89 times 24 hours does.
            (
                "day_rounding_across_a_two_hour_dst_change",
                datetime(2026, 10, 28, 23, 30, tzinfo=UTC),
                "Antarctica/Troll",
                f"toStartOfDay(now() - INTERVAL {FLAG_EVALUATIONS_COMPLETE_DAYS} DAY)",
            ),
        ]
    )
    def test_refuses_a_bound_that_calendar_arithmetic_moves_before_coverage(
        self, _name: str, now: datetime, timezone: str, bound: str
    ):
        with time_machine.travel(now, tick=False):
            assert self._can_read(_bounded_by(bound), timezone=timezone) is False
