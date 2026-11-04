from posthog.test.base import BaseTest

from parameterized import parameterized

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
