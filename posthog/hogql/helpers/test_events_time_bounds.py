from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.compilation import CompilationBudget, compilation_budget
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.helpers.events_time_bounds import reads_events_without_lower_bound
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types

RECENT = "now() - interval 7 day"
EVENT_UUID = "01890cbb-6f6e-7000-8000-000000000001"


class TestReadsEventsWithoutLowerBound(BaseTest):
    @parameterized.expand(
        [
            ("greater_than", f"select count() from events where timestamp > {RECENT}", False),
            ("flipped_comparison", "select count() from events where '2026-01-01' <= timestamp", False),
            ("between", "select count() from events where timestamp between '2026-01-01' and '2026-02-01'", False),
            ("to_date_lower_bound", "select count() from events where toDate(timestamp) >= today() - 7", False),
            ("to_date_equals_today", "select count() from events where toDate(timestamp) = today()", False),
            (
                "wrapped_timestamp",
                "select count() from events where toStartOfDay(toTimeZone(timestamp, 'UTC')) >= '2026-01-01'",
                False,
            ),
            ("prewhere", f"select count() from events prewhere timestamp >= {RECENT}", False),
            ("among_other_filters", f"select count() from events where event = 'a' and timestamp >= {RECENT}", False),
            (
                "every_or_branch_bounded",
                f"select count() from events where (event = 'a' and timestamp > {RECENT}) "
                "or (event = 'b' and timestamp > now() - interval 1 day)",
                False,
            ),
            (
                "scalar_subquery_bound",
                "select count() from events where timestamp > "
                f"(select max(timestamp) from events where timestamp > {RECENT})",
                False,
            ),
            (
                "outer_bound_on_subquery_column",
                f"select count() from (select timestamp from events) where timestamp > {RECENT}",
                False,
            ),
            (
                "outer_bound_on_derived_subquery_column",
                "select count() from (select toStartOfDay(timestamp) as day from events) sub where sub.day >= '2026-01-01'",
                False,
            ),
            (
                "bounded_cte",
                f"with recent as (select event from events where timestamp > {RECENT}) select count() from recent",
                False,
            ),
            (
                "outer_bound_on_cte_column",
                f"with e as (select timestamp, event from events) select count() from e where timestamp > {RECENT}",
                False,
            ),
            (
                "join_with_persons",
                "select count() from events e join persons p on e.person_id = p.id "
                f"where e.timestamp > {RECENT} and p.properties.email = 'a'",
                False,
            ),
            ("lazy_person_join", f"select person.properties.email from events where timestamp > {RECENT}", False),
            ("uuid_lookup", f"select * from events where uuid = '{EVENT_UUID}'", False),
            ("uuid_in_lookup", f"select * from events where uuid in ('{EVENT_UUID}')", False),
            ("uuid_or_lookup", f"select * from events where uuid = '{EVENT_UUID}' or uuid = '{EVENT_UUID}'", False),
            ("constant_to_date", "select count() from events where timestamp >= toDate('2026-01-01')", False),
            ("constant_subtract_days", "select count() from events where timestamp >= subtractDays(now(), 7)", False),
            ("constant_uppercase_now", "select count() from events where timestamp > NOW() - interval 7 day", False),
            (
                "column_date_trunc",
                "select count() from events where dateTrunc('day', timestamp) >= '2026-01-01'",
                False,
            ),
            (
                "column_unix_timestamp",
                "select count() from events where toUnixTimestamp(timestamp) >= 1700000000",
                False,
            ),
            (
                "column_interval_subtracted",
                f"select count() from events where timestamp - interval 1 day > {RECENT}",
                False,
            ),
            ("column_interval_added", f"select count() from events where interval 1 day + timestamp > {RECENT}", False),
            (
                "outer_bound_on_aliased_cte",
                f"with e as (select timestamp from events) select count() from e as x where x.timestamp > {RECENT}",
                False,
            ),
            (
                "outer_bound_on_union_with_persons",
                "select count() from (select timestamp from events union all select created_at as timestamp from persons) "
                f"where timestamp > {RECENT}",
                False,
            ),
            (
                "inner_bound_with_outer_window_column_filter",
                "select * from (select event, row_number() over (partition by distinct_id order by timestamp desc) as rn "
                f"from events where timestamp > {RECENT}) where rn = 1",
                False,
            ),
            (
                "cte_referenced_twice_bounded_inside",
                f"with e as (select event from events where timestamp > {RECENT}) "
                "select count() from e join e as b on e.event = b.event",
                False,
            ),
            ("persons_only", "select count() from persons", False),
            (
                "cte_named_events_over_persons",
                "with events as (select id from persons) select count() from events",
                False,
            ),
            ("bare_read", "select count() from events", True),
            (
                "distinct_id_lookup",
                "select * from events where distinct_id = 'a' order by timestamp desc limit 1",
                True,
            ),
            ("distinct_id_in_aggregate", "select count() from events where distinct_id in ('a', 'b')", True),
            ("upper_bound_only", "select count() from events where timestamp < now()", True),
            ("or_with_unbounded_branch", f"select count() from events where timestamp > {RECENT} or event = 'a'", True),
            (
                "having_only",
                f"select distinct_id from events group by distinct_id having min(timestamp) >= {RECENT}",
                True,
            ),
            ("hour_of_day", "select count() from events where toHour(timestamp) >= 9", True),
            ("age_from_date_difference", "select count() from events where today() - toDate(timestamp) > 30", True),
            ("age_from_minus_call", "select count() from events where minus(today(), toDate(timestamp)) > 30", True),
            ("modulo_of_date", "select count() from events where toDate(timestamp) % 7 >= 1", True),
            ("array_access_column", "select count() from events where splitByChar('/', event)[1] = 'a'", True),
            ("array_access_value", "select count() from events where event = splitByChar('/', distinct_id)[1]", True),
            ("tuple_access_column", "select count() from events where (event, 1).1 = 'a'", True),
            (
                "outer_filter_on_window_column",
                "select * from (select event, row_number() over (partition by distinct_id order by timestamp desc) as rn "
                "from events) where rn = 1",
                True,
            ),
            (
                "outer_bound_across_inner_window",
                "select * from (select timestamp, row_number() over (partition by distinct_id order by timestamp) as rn "
                f"from events) where timestamp > {RECENT}",
                True,
            ),
            (
                "outer_bound_across_inner_limit",
                f"select count() from (select timestamp from events limit 1000) where timestamp > {RECENT}",
                True,
            ),
            (
                "cte_referenced_twice_one_union_branch_bounded",
                f"with e as (select timestamp from events) select count() from e where timestamp > {RECENT} "
                "union all select count() from e",
                True,
            ),
            (
                "cte_referenced_twice_one_join_side_bounded",
                "with e as (select timestamp, event from events) select count() from e join e as b on e.event = b.event "
                f"where e.timestamp > {RECENT}",
                True,
            ),
            ("unbounded_cte", "with e as (select event from events) select count() from e", True),
            (
                "outer_filter_on_other_column",
                "select count() from (select event from events) where event = 'a'",
                True,
            ),
            (
                "outer_bound_on_aggregated_column",
                "select count() from (select distinct_id, max(timestamp) as last_seen from events group by distinct_id) "
                f"where last_seen > {RECENT}",
                True,
            ),
            (
                "unbounded_in_subquery",
                f"select count() from events where timestamp > {RECENT} "
                "and distinct_id in (select distinct_id from events where event = 'a')",
                True,
            ),
            (
                "self_join_one_side_bounded",
                f"select count() from events a join events b on a.uuid = b.uuid where a.timestamp > {RECENT}",
                True,
            ),
            (
                "union_with_unbounded_branch",
                f"select event from events where timestamp > {RECENT} union all select event from events",
                True,
            ),
            (
                "bound_on_scalar_cte",
                "with '2026-01-01' as cutoff select count() from events where timestamp >= cutoff",
                False,
            ),
            (
                "bound_on_select_alias_of_a_constant",
                "select now() - interval 7 day as cutoff, count() from events where timestamp >= cutoff",
                False,
            ),
            (
                "bound_on_alias_of_another_column",
                "select toDateTime(properties.$x) as cutoff, count() from events where timestamp >= cutoff",
                True,
            ),
            (
                "outer_bound_on_union_column_named_in_the_first_branch",
                f"select count() from (select timestamp as t from events union all select timestamp from events) "
                f"where t >= {RECENT}",
                False,
            ),
            (
                "outer_bound_on_union_column_that_a_later_branch_takes_from_elsewhere",
                f"select count() from (select timestamp as t from events union all select created_at from persons "
                f"union all select toDateTime(event) from events) where t >= {RECENT}",
                True,
            ),
            (
                "outer_bound_across_a_union_limit",
                "select count() from ((select timestamp from events union all select timestamp from events) limit 10) "
                f"where timestamp >= {RECENT}",
                True,
            ),
            (
                "join_bound_on_persons_only",
                f"select count() from events e join persons p on e.person_id = p.id where p.created_at > {RECENT}",
                True,
            ),
        ]
    )
    def test_reads_events_without_lower_bound(self, _name: str, sql: str, expected: bool) -> None:
        context = HogQLContext(
            team_id=self.team.pk, database=Database.create_for(team=self.team), enable_select_queries=True
        )
        resolved = resolve_types(parse_select(sql), context, dialect="hogql")

        assert reads_events_without_lower_bound(resolved, context) is expected

    def test_chain_of_shared_ctes_stays_within_the_compilation_budget(self) -> None:
        links = [f"c0 as (select timestamp from events where timestamp > {RECENT})"]
        for level in range(1, 40):
            links.append(
                f"c{level} as (select timestamp from c{level - 1} union all select timestamp from c{level - 1})"
            )
        context = HogQLContext(
            team_id=self.team.pk, database=Database.create_for(team=self.team), enable_select_queries=True
        )
        resolved = resolve_types(
            parse_select(f"with {', '.join(links)} select count() from c39"), context, dialect="hogql"
        )

        token = compilation_budget.set(CompilationBudget())
        try:
            assert reads_events_without_lower_bound(resolved, context) is False
        finally:
            compilation_budget.reset(token)
