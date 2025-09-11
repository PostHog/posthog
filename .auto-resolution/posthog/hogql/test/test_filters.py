from typing import Any, Optional

from posthog.test.base import BaseTest

from posthog.schema import DateRange, EventPropertyFilter, GroupPropertyFilter, HogQLFilters, PersonPropertyFilter

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.visitor import clear_locations


class TestFilters(BaseTest):
    maxDiff = None

    def _parse_expr(self, expr: str, placeholders: Optional[dict[str, Any]] = None):
        return clear_locations(parse_expr(expr, placeholders=placeholders))

    def _parse_select(self, select: str, placeholders: Optional[dict[str, Any]] = None):
        return clear_locations(parse_select(select, placeholders=placeholders))

    def _print_ast(self, node: ast.Expr):
        return print_ast(
            node,
            dialect="hogql",
            context=HogQLContext(team_id=self.team.pk, enable_select_queries=True),
        )

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
        select = self._parse_select("SELECT person FROM persons where {filters}")

        with self.assertRaisesMessage(
            QueryError,
            "Cannot use 'filters' placeholder in a SELECT clause that does not select from the events, sessions, logs or groups table.",
        ):
            replace_filters(select, None, self.team)

        with self.assertRaisesMessage(
            QueryError,
            "Cannot use 'filters' placeholder in a SELECT clause that does not select from the events, sessions, logs or groups table.",
        ):
            replace_filters(select, HogQLFilters(), self.team)

    def test_raises_when_filters_and_not_events_or_sessions(self):
        select = self._parse_select("SELECT person FROM persons where {filters}")

        with self.assertRaisesMessage(
            QueryError,
            "Cannot use 'filters' placeholder in a SELECT clause that does not select from the events, sessions, logs or groups table.",
        ):
            replace_filters(select, HogQLFilters(dateRange=DateRange(date_from="2020-02-02")), self.team)

    def test_replace_filters_date_range(self):
        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(dateRange=DateRange(date_from="2020-02-02")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE greaterOrEquals(timestamp, toDateTime('2020-02-02 00:00:00.000000')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(dateRange=DateRange(date_to="2020-02-02")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT event FROM events WHERE less(timestamp, toDateTime('2020-02-02 00:00:00.000000')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

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
        select = replace_filters(
            self._parse_select("SELECT group_key FROM groups where {filters}"),
            HogQLFilters(dateRange=DateRange(date_from="2020-02-02")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT group_key FROM groups WHERE greaterOrEquals(created_at, toDateTime('2020-02-02 00:00:00.000000')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

        select = replace_filters(
            self._parse_select("SELECT group_key FROM groups where {filters}"),
            HogQLFilters(dateRange=DateRange(date_to="2020-02-02")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            f"SELECT group_key FROM groups WHERE less(created_at, toDateTime('2020-02-02 00:00:00.000000')) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

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
            f"greaterOrEquals(created_at, toDateTime('2020-02-02 00:00:00.000000'))) LIMIT {MAX_SELECT_RETURNED_ROWS}",
        )

    def test_raises_when_filters_and_not_supported_table_includes_groups(self):
        select = self._parse_select("SELECT person FROM persons where {filters}")

        with self.assertRaisesMessage(
            QueryError,
            "Cannot use 'filters' placeholder in a SELECT clause that does not select from the events, sessions, logs or groups table.",
        ):
            replace_filters(select, HogQLFilters(dateRange=DateRange(date_from="2020-02-02")), self.team)
