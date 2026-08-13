from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    CohortPropertyFilter,
    DateRange,
    ElementPropertyFilter,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    HogQLFilters,
    HogQLPropertyFilter,
    IntervalType,
    PersonPropertyFilter,
    RecordingPropertyFilter,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.visitor import clear_locations

from products.cohorts.backend.models.cohort import Cohort


class TestFilters(BaseTest):
    maxDiff = None

    def _parse_expr(self, expr: str, placeholders: Optional[dict[str, Any]] = None):
        return clear_locations(parse_expr(expr, placeholders=placeholders))

    def _parse_select(self, select: str, placeholders: Optional[dict[str, Any]] = None):
        return clear_locations(parse_select(select, placeholders=placeholders))

    def _print_ast(self, node: ast.Expr):
        return prepare_and_print_ast(
            node,
            dialect="hogql",
            context=HogQLContext(team_id=self.team.pk, enable_select_queries=True),
        )[0]

    def test_replace_filters_empty(self):
        select = replace_filters(self._parse_select("SELECT event FROM events"), HogQLFilters(), self.team)
        self.assertEqual(self._print_ast(select), f"SELECT event FROM events LIMIT {MAX_SELECT_RETURNED_ROWS}")

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select), f"SELECT event FROM events WHERE true LIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            None,
            self.team,
        )
        self.assertEqual(
            self._print_ast(select), f"SELECT event FROM events WHERE true LIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

    def test_raises_when_filters_empty_and_not_events_or_sessions(self):
        select = self._parse_select("SELECT type FROM heatmaps where {filters}")

        with self.assertRaisesMessage(
            QueryError,
            "Cannot use 'filters' placeholder in a SELECT clause that does not select from",
        ):
            replace_filters(select, None, self.team)

        with self.assertRaisesMessage(
            QueryError,
            "Cannot use 'filters' placeholder in a SELECT clause that does not select from",
        ):
            replace_filters(select, HogQLFilters(), self.team)

    def test_raises_when_filters_and_not_events_or_sessions(self):
        select = self._parse_select("SELECT type FROM heatmaps where {filters}")

        with self.assertRaisesMessage(
            QueryError,
            "Cannot use 'filters' placeholder in a SELECT clause that does not select from",
        ):
            replace_filters(select, HogQLFilters(dateRange=DateRange(date_from="2020-02-02")), self.team)

    def test_replace_filters_date_range(self):
        with freeze_time("2020-02-15T13:37:42Z"):
            # open-ended range: bounded at the end of today instead of including future-dated rows
            select = replace_filters(
                self._parse_select("SELECT event FROM events where {filters}"),
                HogQLFilters(dateRange=DateRange(date_from="2020-02-02")),
                self.team,
            )
            self.assertEqual(
                self._print_ast(select),
                "SELECT event FROM events WHERE "
                "and(lessOrEquals(timestamp, toDateTime('2020-02-15 23:59:59.999999')), "
                f"greaterOrEquals(timestamp, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
            )

        # a date-only upper bound covers that whole day
        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(dateRange=DateRange(date_to="2020-02-02")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE lessOrEquals(timestamp, toDateTime('2020-02-02 23:59:59.999999')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        # an explicit datetime upper bound is used verbatim and compared exclusively
        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(dateRange=DateRange(date_from="2020-02-02", date_to="2020-02-03 23:59:59")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events WHERE "
            "and(less(timestamp, toDateTime('2020-02-03 23:59:59.000000')), "
            f"greaterOrEquals(timestamp, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        # now with different team timezone
        self.team.timezone = "America/New_York"
        self.team.save()

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(dateRange=DateRange(date_from="2020-02-02", date_to="2020-02-03 23:59:59")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events WHERE "
            "and(less(timestamp, toDateTime('2020-02-03 23:59:59.000000')), "
            f"greaterOrEquals(timestamp, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_date_range_with_timezone(self):
        # now with different team timezone
        self.team.timezone = "America/New_York"
        self.team.save()

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(dateRange=DateRange(date_from="2020-02-02", date_to="2020-02-03 23:59:59Z")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events WHERE "
            "and(less(timestamp, toDateTime('2020-02-03 18:59:59.000000')), "
            f"greaterOrEquals(timestamp, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    @parameterized.expand(
        [
            ("mStart", "2020-02-01 00:00:00.000000"),
            ("-7d", "2020-02-08 00:00:00.000000"),
            ("yStart", "2020-01-01 00:00:00.000000"),
            ("wStart", "2020-02-09 00:00:00.000000"),  # frozen date is a Saturday; weeks start on Sunday by default
        ]
    )
    def test_replace_filters_relative_date_from_snaps_to_start_of_day(self, date_from: str, expected: str):
        # Regression: relative presets used to keep the wall-clock time of day, so "This month" on a
        # dashboard silently dropped rows between midnight and the current time on the first day
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select("SELECT event FROM events WHERE timestamp >= {filters.dateRange.from}"),
                HogQLFilters(dateRange=DateRange(date_from=date_from)),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE greaterOrEquals(timestamp, toDateTime('{expected}')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_date_from_respects_week_start_day(self):
        self.team.week_start_day = 1
        self.team.save()
        with freeze_time("2020-02-15T13:37:42Z"):  # a Saturday
            select = replace_filters(
                self._parse_select("SELECT event FROM events WHERE timestamp >= {filters.dateRange.from}"),
                HogQLFilters(dateRange=DateRange(date_from="wStart")),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE greaterOrEquals(timestamp, toDateTime('2020-02-10 00:00:00.000000')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_sub_day_date_from_stays_rolling(self):
        # Sub-day ranges ("last 1 hour" in logs/traces) must keep their exact lower bound and stay
        # open-ended — snapping them to calendar boundaries would change the window's meaning
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select("SELECT event FROM events where {filters}"),
                HogQLFilters(dateRange=DateRange(date_from="-1h")),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE greaterOrEquals(timestamp, toDateTime('2020-02-15 12:37:42.000000')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    @parameterized.expand(
        [
            (None, "2020-02-15 23:59:59.999999"),  # open-ended → end of today
            ("-1mEnd", "2020-01-31 23:59:59.999999"),  # relative → end of that day
            ("2020-02-10", "2020-02-10 23:59:59.999999"),  # date-only → end of that day
            ("2020-02-10 12:34:56", "2020-02-10 12:34:56.000000"),  # explicit datetime → verbatim
            ("-30M", "2020-02-15 13:07:42.000000"),  # sub-day relative → exact rolling bound, no snapping
        ]
    )
    def test_replace_filters_date_to_resolution(self, date_to: Optional[str], expected: str):
        # Regression: an unset date_to used to drop the upper bound entirely, so "This month" and
        # "Last 7 days" included future-dated rows
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select("SELECT event FROM events WHERE timestamp <= {filters.dateRange.to}"),
                HogQLFilters(dateRange=DateRange(date_from="-7d", date_to=date_to)),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE lessOrEquals(timestamp, toDateTime('{expected}')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_open_ended_date_to_uses_team_timezone(self):
        self.team.timezone = "America/New_York"
        self.team.save()
        with freeze_time("2020-02-15T03:00:00Z"):  # still Feb 14 in New York
            select = replace_filters(
                self._parse_select("SELECT event FROM events WHERE timestamp <= {filters.dateRange.to}"),
                HogQLFilters(dateRange=DateRange(date_from="-7d")),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE lessOrEquals(timestamp, toDateTime('2020-02-14 23:59:59.999999')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    @parameterized.expand(
        [
            ("2020-02-10", "2020-02-10 00:00:00.000000"),  # date-only stays at midnight
            (None, "2020-02-15 13:37:42.000000"),  # open-ended resolves to now verbatim
        ]
    )
    def test_replace_filters_date_to_with_explicit_date(self, date_to: Optional[str], expected: str):
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select("SELECT event FROM events WHERE timestamp <= {filters.dateRange.to}"),
                HogQLFilters(dateRange=DateRange(date_from="2020-02-01", date_to=date_to, explicitDate=True)),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE lessOrEquals(timestamp, toDateTime('{expected}')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    @parameterized.expand(
        [
            ("no_date_range", HogQLFilters(properties=[])),
            ("empty_date_range", HogQLFilters(dateRange=DateRange())),
            ("rolling_date_from", HogQLFilters(dateRange=DateRange(date_from="-1h"))),
            ("all_time_date_from", HogQLFilters(dateRange=DateRange(date_from="all"))),
        ]
    )
    def test_replace_filters_date_to_placeholder_skipped_when_open_ended(self, _name: str, filters: HogQLFilters):
        select = replace_filters(
            self._parse_select("SELECT event FROM events WHERE timestamp <= {filters.dateRange.to}"),
            filters,
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE equals(true, true) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_all_time_stays_unbounded(self):
        # "All time" must not gain an end-of-today cap: unlike QueryDateRange (where "all" means
        # "since the first event"), here it promises the whole table, including future-dated
        # warehouse rows
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select("SELECT event FROM events where {filters}"),
                HogQLFilters(dateRange=DateRange(date_from="all")),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE true LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_this_month_preset(self):
        # The exact shape a dashboard's "This month" filter produces: date_from="mStart", no date_to
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select("SELECT event FROM events where {filters}"),
                HogQLFilters(dateRange=DateRange(date_from="mStart")),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events WHERE "
            "and(lessOrEquals(timestamp, toDateTime('2020-02-15 23:59:59.999999')), "
            f"greaterOrEquals(timestamp, toDateTime('2020-02-01 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_event_property(self):
        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(
                properties=[EventPropertyFilter(key="random_uuid", operator="exact", value="123", type="event")]
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE equals(properties.random_uuid, '123') LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_person_property(self):
        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(
                properties=[PersonPropertyFilter(key="random_uuid", operator="exact", value="123", type="person")]
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE equals(person.properties.random_uuid, '123') LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(
                properties=[
                    EventPropertyFilter(key="random_uuid", operator="exact", value="123", type="event"),
                    PersonPropertyFilter(key="random_uuid", operator="exact", value="123", type="person"),
                ]
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE and(equals(properties.random_uuid, '123'), equals(person.properties.random_uuid, '123')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_test_accounts(self):
        self.team.test_account_filters = [
            {
                "key": "email",
                "type": "person",
                "value": "posthog.com",
                "operator": "not_icontains",
            }
        ]
        self.team.save()

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(filterTestAccounts=True),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE notILike(toString(person.properties.email), '%posthog.com%') LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_groups_empty(self):
        select = replace_filters(self._parse_select("SELECT group_key FROM groups"), HogQLFilters(), self.team)
        self.assertEqual(self._print_ast(select), f"SELECT group_key FROM groups LIMIT {MAX_SELECT_RETURNED_ROWS}")

        select = replace_filters(
            self._parse_select("SELECT group_key FROM groups where {filters}"),
            HogQLFilters(),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select), f"SELECT group_key FROM groups WHERE true LIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

        select = replace_filters(
            self._parse_select("SELECT group_key FROM groups where {filters}"),
            None,
            self.team,
        )
        self.assertEqual(
            self._print_ast(select), f"SELECT group_key FROM groups WHERE true LIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

    def test_replace_filters_groups_date_range(self):
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select("SELECT group_key FROM groups where {filters}"),
                HogQLFilters(dateRange=DateRange(date_from="2020-02-02")),
                self.team,
            )
            self.assertEqual(
                self._print_ast(select),
                "SELECT group_key FROM groups WHERE "
                "and(lessOrEquals(created_at, toDateTime('2020-02-15 23:59:59.999999')), "
                f"greaterOrEquals(created_at, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
            )

        select = replace_filters(
            self._parse_select("SELECT group_key FROM groups where {filters}"),
            HogQLFilters(dateRange=DateRange(date_to="2020-02-02")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT group_key FROM groups WHERE lessOrEquals(created_at, toDateTime('2020-02-02 23:59:59.999999')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        # an explicit datetime upper bound is used verbatim and compared exclusively
        select = replace_filters(
            self._parse_select("SELECT group_key FROM groups where {filters}"),
            HogQLFilters(dateRange=DateRange(date_from="2020-02-02", date_to="2020-02-03 23:59:59")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT group_key FROM groups WHERE "
            "and(less(created_at, toDateTime('2020-02-03 23:59:59.000000')), "
            f"greaterOrEquals(created_at, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_groups_property(self):
        select = replace_filters(
            self._parse_select("SELECT group_key FROM groups where {filters}"),
            HogQLFilters(
                properties=[
                    GroupPropertyFilter(
                        key="company_name", operator="exact", value="PostHog", type="group", group_type_index=0
                    )
                ]
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT group_key FROM groups WHERE equals(properties.company_name, 'PostHog') LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_groups_multiple_properties(self):
        select = replace_filters(
            self._parse_select("SELECT group_key FROM groups where {filters}"),
            HogQLFilters(
                properties=[
                    GroupPropertyFilter(
                        key="company_name", operator="exact", value="PostHog", type="group", group_type_index=0
                    ),
                    GroupPropertyFilter(
                        key="industry", operator="exact", value="Software", type="group", group_type_index=0
                    ),
                ]
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT group_key FROM groups WHERE and(equals(properties.company_name, 'PostHog'), equals(properties.industry, 'Software')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_groups_date_and_properties(self):
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select("SELECT group_key FROM groups where {filters}"),
                HogQLFilters(
                    dateRange=DateRange(date_from="2020-02-02"),
                    properties=[
                        GroupPropertyFilter(
                            key="company_name", operator="exact", value="PostHog", type="group", group_type_index=0
                        )
                    ],
                ),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            "SELECT group_key FROM groups WHERE "
            "and(equals(properties.company_name, 'PostHog'), "
            "lessOrEquals(created_at, toDateTime('2020-02-15 23:59:59.999999')), "
            f"greaterOrEquals(created_at, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_raises_when_filters_and_not_supported_table_includes_groups(self):
        select = self._parse_select("SELECT type FROM heatmaps where {filters}")

        with self.assertRaisesMessage(
            QueryError,
            "Cannot use 'filters' placeholder in a SELECT clause that does not select from",
        ):
            replace_filters(select, HogQLFilters(dateRange=DateRange(date_from="2020-02-02")), self.team)

    def test_replace_filters_persons_empty(self):
        select = replace_filters(
            self._parse_select("SELECT id FROM persons where {filters}"),
            HogQLFilters(),
            self.team,
        )
        self.assertEqual(self._print_ast(select), f"SELECT id FROM persons WHERE true LIMIT {MAX_SELECT_RETURNED_ROWS}")

        select = replace_filters(
            self._parse_select("SELECT id FROM persons where {filters}"),
            None,
            self.team,
        )
        self.assertEqual(self._print_ast(select), f"SELECT id FROM persons WHERE true LIMIT {MAX_SELECT_RETURNED_ROWS}")

    def test_replace_filters_persons_date_range(self):
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select("SELECT id FROM persons where {filters}"),
                HogQLFilters(dateRange=DateRange(date_from="2020-02-02")),
                self.team,
            )
            self.assertEqual(
                self._print_ast(select),
                "SELECT id FROM persons WHERE "
                "and(lessOrEquals(created_at, toDateTime('2020-02-15 23:59:59.999999')), "
                f"greaterOrEquals(created_at, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
            )

    def test_replace_filters_persons_property(self):
        select = replace_filters(
            self._parse_select("SELECT id FROM persons where {filters}"),
            HogQLFilters(
                properties=[PersonPropertyFilter(key="email", operator="exact", value="max@example.com", type="person")]
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT id FROM persons WHERE equals(properties.email, 'max@example.com') LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_persons_event_property_raises(self):
        select = self._parse_select("SELECT id FROM persons where {filters}")

        with self.assertRaisesMessage(
            QueryError,
            "The 'event' property filter does not work in 'person' scope",
        ):
            replace_filters(
                select,
                HogQLFilters(
                    properties=[EventPropertyFilter(key="$browser", operator="exact", value="Chrome", type="event")]
                ),
                self.team,
            )

    def test_replace_filters_persons_test_accounts(self):
        self.team.test_account_filters = [
            {
                "key": "email",
                "type": "person",
                "value": "posthog.com",
                "operator": "not_icontains",
            }
        ]
        self.team.save()

        select = replace_filters(
            self._parse_select("SELECT id FROM persons where {filters}"),
            HogQLFilters(filterTestAccounts=True),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT id FROM persons WHERE notILike(toString(properties.email), '%posthog.com%') LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_persons_test_accounts_cohort(self):
        # The default test account filter on a new project excludes a cohort, and the cohort branch of
        # property_to_expr picks the right column per scope, so person scope resolves it fine.
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "email", "value": "posthog.com", "type": "person"}]}],
        )
        self.team.test_account_filters = [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "not_in"}]
        self.team.save()

        select = replace_filters(
            self._parse_select("SELECT id FROM persons where {filters}"),
            HogQLFilters(filterTestAccounts=True),
            self.team,
        )
        # Printing expands the cohort into a subquery. The point of the assertion is the left side:
        # person scope binds the membership check to persons.id, and it resolves.
        self.assertEqual(
            self._print_ast(select),
            "SELECT id FROM persons WHERE notIn(id, (SELECT person_id FROM raw_cohort_people "
            f"WHERE equals(cohort_id, {cohort.pk}) GROUP BY person_id, cohort_id, version "
            f"HAVING greater(sum(sign), 0))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_replace_filters_persons_test_accounts_event_property_raises(self):
        self.team.test_account_filters = [
            {
                "key": "$host",
                "type": "event",
                "value": "localhost",
                "operator": "not_icontains",
            }
        ]
        self.team.save()

        select = self._parse_select("SELECT id FROM persons where {filters}")

        with self.assertRaisesMessage(
            QueryError,
            "A test account filter in your project settings (the event property filter on '$host') "
            "can't apply to a query that selects only from persons.",
        ):
            replace_filters(select, HogQLFilters(filterTestAccounts=True), self.team)

    def test_replace_filters_events_joined_with_persons_keep_event_scope(self):
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select(
                    "SELECT event FROM events JOIN persons ON events.person_id = persons.id where {filters}"
                ),
                HogQLFilters(
                    dateRange=DateRange(date_from="2020-02-02"),
                    properties=[
                        PersonPropertyFilter(key="email", operator="exact", value="max@example.com", type="person")
                    ],
                ),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events JOIN persons ON equals(events.person_id, persons.id) WHERE "
            "and(equals(person.properties.email, 'max@example.com'), "
            "lessOrEquals(timestamp, toDateTime('2020-02-15 23:59:59.999999')), "
            f"greaterOrEquals(timestamp, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_raises_for_unsupported_filters_placeholder(self):
        select = self._parse_select("SELECT dateTrunc({filters.granularity}, timestamp) FROM events WHERE {filters}")

        with self.assertRaisesMessage(
            QueryError,
            "Unsupported filters placeholder `{filters.granularity}`",
        ):
            replace_filters(select, HogQLFilters(), self.team)

    def test_bound_filters_date_range_and_property(self):
        # persons is a table the plain {filters} placeholder rejects, so this exercises the unlock
        with freeze_time("2020-02-15T13:37:42Z"):
            select = replace_filters(
                self._parse_select(
                    "SELECT id FROM persons WHERE {filters(created_at AS timestamp, properties.plan AS 'plan')}"
                ),
                HogQLFilters(
                    dateRange=DateRange(date_from="2020-02-02"),
                    properties=[EventPropertyFilter(key="plan", operator="exact", value="hobby", type="event")],
                ),
                self.team,
            )
        self.assertEqual(
            self._print_ast(select),
            "SELECT id FROM persons WHERE "
            "and(lessOrEquals(created_at, toDateTime('2020-02-15 23:59:59.999999')), "
            "greaterOrEquals(created_at, toDateTime('2020-02-02 00:00:00.000000')), "
            f"equals(properties.plan, 'hobby')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_bound_filters_without_filters_resolve_to_true(self):
        for filters in [None, HogQLFilters()]:
            select = replace_filters(
                self._parse_select("SELECT id FROM persons WHERE {filters(created_at AS timestamp)}"),
                filters,
                self.team,
            )
            self.assertEqual(
                self._print_ast(select),
                f"SELECT id FROM persons WHERE true LIMIT {MAX_SELECT_RETURNED_ROWS}",
            )

    def test_bound_filters_null_bindings_skip_filters(self):
        select = replace_filters(
            self._parse_select("SELECT id FROM persons WHERE {filters(null AS timestamp, null AS 'plan')}"),
            HogQLFilters(
                dateRange=DateRange(date_from="2020-02-02", date_to="2020-02-03"),
                properties=[EventPropertyFilter(key="plan", operator="exact", value="hobby", type="event")],
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT id FROM persons WHERE true LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    @parameterized.expand(
        [
            (
                "multi_value_exact_in",
                EventPropertyFilter(key="plan", operator="exact", value=["hobby", "scale"], type="event"),
                "in(properties.plan, tuple('hobby', 'scale'))",
            ),
            (
                "multi_value_is_not",
                EventPropertyFilter(key="plan", operator="is_not", value=["hobby", "scale"], type="event"),
                "notIn(properties.plan, tuple('hobby', 'scale'))",
            ),
            (
                "person_property_binds_by_key",
                PersonPropertyFilter(key="plan", operator="icontains", value="hobby", type="person"),
                "ilike(toString(properties.plan), '%hobby%')",
            ),
            (
                "group_key_values_stringified",
                EventMetadataPropertyFilter(key="$group_0", operator="exact", value=[123, 456], type="event_metadata"),
                "in(properties.plan, tuple('123', '456'))",
            ),
        ]
    )
    def test_bound_filters_operator_semantics(self, _name, property_filter, expected_where):
        key = property_filter.key
        select = replace_filters(
            self._parse_select("SELECT id FROM persons WHERE {filters(properties.plan AS '" + key + "')}"),
            HogQLFilters(properties=[property_filter]),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT id FROM persons WHERE {expected_where} LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_bound_filters_unbound_property_raises(self):
        select = self._parse_select("SELECT id FROM persons WHERE {filters(null AS timestamp)}")
        with self.assertRaisesMessage(
            QueryError,
            "The property filter on 'plan' has no binding in {filters(...)}",
        ):
            replace_filters(
                select,
                HogQLFilters(
                    properties=[EventPropertyFilter(key="plan", operator="exact", value="hobby", type="event")]
                ),
                self.team,
            )

    def test_bound_filters_date_range_requires_timestamp_binding(self):
        select = self._parse_select("SELECT id FROM persons WHERE {filters(properties.plan AS 'plan')}")

        with self.assertRaisesMessage(
            QueryError,
            "A date filter is set, but {filters(...)} has no timestamp binding",
        ):
            replace_filters(select, HogQLFilters(dateRange=DateRange(date_from="2020-02-02")), self.team)

        # without an active date filter the missing timestamp binding is fine
        select = replace_filters(
            self._parse_select("SELECT id FROM persons WHERE {filters(properties.plan AS 'plan')}"),
            HogQLFilters(properties=[EventPropertyFilter(key="plan", operator="exact", value="hobby", type="event")]),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT id FROM persons WHERE equals(properties.plan, 'hobby') LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    @parameterized.expand(
        [
            ("positional_argument", "{filters(created_at)}", "must bind an expression to a filter key with AS"),
            ("no_arguments", "{filters()}", "must bind an expression to a filter key with AS"),
            (
                "duplicate_binding",
                "{filters(created_at AS timestamp, id AS timestamp)}",
                "Filter key 'timestamp' is bound more than once",
            ),
        ]
    )
    def test_bound_filters_usage_errors(self, _name, placeholder, expected_message):
        select = self._parse_select(f"SELECT id FROM persons WHERE {placeholder}")
        with self.assertRaisesMessage(QueryError, expected_message):
            replace_filters(select, HogQLFilters(), self.team)

    @parameterized.expand(
        [
            (
                "cohort",
                CohortPropertyFilter(key="id", value=42, type="cohort"),
                "Cohort filters can't be applied through {filters(...)} bindings",
            ),
            (
                "hogql",
                HogQLPropertyFilter(key="properties.x = 1", type="hogql"),
                "SQL expression filters can't be applied through {filters(...)} bindings",
            ),
            (
                "element",
                ElementPropertyFilter(key="selector", operator="exact", value=".sign-up", type="element"),
                "Element filters match autocaptured elements and can't be applied through {filters(...)} bindings",
            ),
            (
                "recording",
                RecordingPropertyFilter(key="visited_page", operator="icontains", value="/pricing", type="recording"),
                "Session recording filters can't be applied through {filters(...)} bindings",
            ),
        ]
    )
    def test_bound_filters_unbindable_filter_types_raise(self, _name, property_filter, expected_message):
        select = self._parse_select("SELECT id FROM persons WHERE {filters(created_at AS timestamp)}")
        with self.assertRaisesMessage(QueryError, expected_message):
            replace_filters(select, HogQLFilters(properties=[property_filter]), self.team)

    def test_bound_filters_apply_test_account_filters(self):
        self.team.test_account_filters = [
            {"key": "email", "type": "person", "value": "posthog.com", "operator": "not_icontains"}
        ]
        self.team.save()

        select = replace_filters(
            self._parse_select("SELECT id FROM persons WHERE {filters(properties.email AS 'email')}"),
            HogQLFilters(filterTestAccounts=True),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT id FROM persons WHERE "
            f"notILike(toString(properties.email), '%posthog.com%') LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        select = self._parse_select("SELECT id FROM persons WHERE {filters(null AS timestamp)}")
        with self.assertRaisesMessage(
            QueryError,
            "The test account filter on 'email' has no binding in {filters(...)}",
        ):
            replace_filters(select, HogQLFilters(filterTestAccounts=True), self.team)

    @parameterized.expand(
        [
            ("bare_defaults_to_day", "{filters.interval}", HogQLFilters(), "day"),
            ("bare_uses_dashboard_interval", "{filters.interval}", HogQLFilters(interval=IntervalType.WEEK), "week"),
            ("call_argument_is_the_author_default", "{filters.interval('week')}", None, "week"),
            (
                "dashboard_interval_beats_author_default",
                "{filters.interval('week')}",
                HogQLFilters(interval=IntervalType.MONTH),
                "month",
            ),
        ]
    )
    def test_interval_placeholder(self, _name, placeholder, filters, expected_unit):
        select = replace_filters(
            self._parse_select("SELECT dateTrunc(" + placeholder + ", timestamp) FROM events"),
            filters,
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT dateTrunc('{expected_unit}', timestamp) FROM events LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    @parameterized.expand(
        [
            ("two_arguments", "{filters.interval('day', 'week')}", "takes at most one argument"),
            ("non_constant_default", "{filters.interval(timestamp)}", "must be a constant string"),
            ("unknown_unit", "{filters.interval('fortnight')}", "must be a constant string"),
        ]
    )
    def test_interval_placeholder_usage_errors(self, _name, placeholder, expected_message):
        select = self._parse_select(f"SELECT dateTrunc({placeholder}, timestamp) FROM events")
        with self.assertRaisesMessage(QueryError, expected_message):
            replace_filters(select, HogQLFilters(), self.team)

    @parameterized.expand(
        [
            ("single_breakdown", BreakdownFilter(breakdown="plan", breakdown_type="event")),
            ("single_entry_breakdowns_list", BreakdownFilter(breakdowns=[Breakdown(property="plan", type="event")])),
        ]
    )
    def test_breakdown_placeholder_binds_the_selected_key(self, _name, breakdown_filter):
        select = replace_filters(
            self._parse_select(
                "SELECT {filters.breakdown(properties.plan AS 'plan', properties.region AS 'region')} AS breakdown, "
                "count() FROM persons GROUP BY breakdown"
            ),
            HogQLFilters(breakdownFilter=breakdown_filter),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT properties.plan AS breakdown, count() FROM persons "
            f"GROUP BY breakdown LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_breakdown_placeholder_without_breakdown_yields_single_group(self):
        for filters in [None, HogQLFilters()]:
            select = replace_filters(
                self._parse_select(
                    "SELECT {filters.breakdown(properties.plan AS 'plan')} AS breakdown, count() "
                    "FROM persons GROUP BY breakdown"
                ),
                filters,
                self.team,
            )
            self.assertEqual(
                self._print_ast(select),
                f"SELECT NULL AS breakdown, count() FROM persons GROUP BY breakdown LIMIT {MAX_SELECT_RETURNED_ROWS}",
            )

    def test_breakdown_placeholder_null_binding_opts_out(self):
        select = replace_filters(
            self._parse_select(
                "SELECT {filters.breakdown(null AS 'plan')} AS breakdown, count() FROM persons GROUP BY breakdown"
            ),
            HogQLFilters(breakdownFilter=BreakdownFilter(breakdown="plan", breakdown_type="event")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT NULL AS breakdown, count() FROM persons GROUP BY breakdown LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_breakdown_placeholder_unbound_key_raises(self):
        select = self._parse_select(
            "SELECT {filters.breakdown(properties.region AS 'region')} AS breakdown, count() "
            "FROM persons GROUP BY breakdown"
        )
        with self.assertRaisesMessage(
            QueryError,
            "The breakdown on 'plan' has no binding in {filters.breakdown(...)}",
        ):
            replace_filters(
                select,
                HogQLFilters(breakdownFilter=BreakdownFilter(breakdown="plan", breakdown_type="event")),
                self.team,
            )

    @parameterized.expand(
        [
            (
                "cohort_breakdown",
                BreakdownFilter(breakdown=42, breakdown_type="cohort"),
                "Cohort breakdowns can't be applied",
            ),
            (
                "cohort_in_breakdowns_list",
                BreakdownFilter(breakdowns=[Breakdown(property=42, type="cohort")]),
                "Cohort breakdowns can't be applied",
            ),
            (
                "histogram_binning",
                BreakdownFilter(breakdown="plan", breakdown_type="event", breakdown_histogram_bin_count=10),
                "Numeric binning isn't supported",
            ),
            (
                "histogram_in_breakdowns_list",
                BreakdownFilter(breakdowns=[Breakdown(property="plan", type="event", histogram_bin_count=10)]),
                "Numeric binning isn't supported",
            ),
            (
                "multiple_breakdowns",
                BreakdownFilter(
                    breakdowns=[Breakdown(property="plan", type="event"), Breakdown(property="region", type="event")]
                ),
                "supports a single breakdown",
            ),
        ]
    )
    def test_breakdown_placeholder_unsupported_shapes_raise(self, _name, breakdown_filter, expected_message):
        select = self._parse_select(
            "SELECT {filters.breakdown(properties.plan AS 'plan')} AS breakdown FROM persons GROUP BY breakdown"
        )
        with self.assertRaisesMessage(QueryError, expected_message):
            replace_filters(select, HogQLFilters(breakdownFilter=breakdown_filter), self.team)

    @parameterized.expand(
        [
            ("bare_chain", "{filters.breakdown}", "needs column bindings"),
            (
                "positional_argument",
                "{filters.breakdown(properties.plan)}",
                "must bind an expression to a breakdown key",
            ),
            ("unsupported_call", "{filters.dateRange(day AS timestamp)}", "Unsupported filters placeholder"),
        ]
    )
    def test_breakdown_placeholder_usage_errors(self, _name, placeholder, expected_message):
        select = self._parse_select(f"SELECT {placeholder} AS breakdown FROM persons")
        with self.assertRaisesMessage(QueryError, expected_message):
            replace_filters(select, HogQLFilters(), self.team)
