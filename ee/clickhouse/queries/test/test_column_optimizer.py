from ee.clickhouse.materialized_columns import materialize
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models import Action, ActionStep
from posthog.models.filters import Filter
from posthog.test.base import APIBaseTest

BASE_FILTER = Filter({"events": [{"id": "$pageview", "type": "events", "order": 0}]})

FILTER_BY_TEST_ACCOUNTS = BASE_FILTER.with_data({"filter_test_accounts": True})
FILTER_WITH_PROPERTIES = BASE_FILTER.with_data(
    {
        "properties": [
            {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
            {"key": "person_prop", "value": "efg", "type": "person"},
            {"key": "id", "value": 1, "type": "cohort"},
            {"key": "tag_name", "value": ["label"], "operator": "exact", "type": "element"},
        ]
    }
)


class TestColumnOptimizer(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.test_account_filters = [
            {"key": "email", "type": "person", "value": "posthog.com", "operator": "not_icontains"},
            {
                "key": "$host",
                "type": "event",
                "value": ["127.0.0.1:3000", "127.0.0.1:5000", "localhost:5000", "localhost:8000"],
                "operator": "is_not",
            },
            {"key": "distinct_id", "type": "event", "value": "posthog.com", "operator": "not_icontains"},
        ]
        self.team.save()

    def column_optimizer(self, filter: Filter):
        return ColumnOptimizer(filter, self.team.id)

    def test_properties_used_in_filter(self):
        properties_used_in_filter = lambda filter: ColumnOptimizer(filter, self.team.id).properties_used_in_filter

        self.assertEqual(properties_used_in_filter(BASE_FILTER), set())
        self.assertEqual(
            properties_used_in_filter(FILTER_BY_TEST_ACCOUNTS),
            {("$host", "event"), ("distinct_id", "event"), ("email", "person")},
        )
        self.assertEqual(
            properties_used_in_filter(FILTER_WITH_PROPERTIES),
            {("event_prop", "event"), ("person_prop", "person"), ("id", "cohort"), ("tag_name", "element")},
        )

        # Breakdown cases
        filter = BASE_FILTER.with_data({"breakdown": "some_prop", "breakdown_type": "person"})
        self.assertEqual(properties_used_in_filter(filter), {("some_prop", "person")})

        filter = BASE_FILTER.with_data({"breakdown": "some_prop", "breakdown_type": "event"})
        self.assertEqual(properties_used_in_filter(filter), {("some_prop", "event")})

        filter = BASE_FILTER.with_data({"breakdown": [11], "breakdown_type": "cohort"})
        self.assertEqual(properties_used_in_filter(filter), set())

        filter = Filter(
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "math": "sum",
                        "math_property": "numeric_prop",
                        "properties": [
                            {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
                            {"key": "person_prop", "value": "efg", "type": "person"},
                            {"key": "id", "value": 1, "type": "cohort"},
                            {"key": "tag_name", "value": ["label"], "operator": "exact", "type": "element"},
                        ],
                    }
                ]
            }
        )
        self.assertEqual(
            properties_used_in_filter(filter),
            {
                ("numeric_prop", "event"),
                ("event_prop", "event"),
                ("person_prop", "person"),
                ("id", "cohort"),
                ("tag_name", "element"),
            },
        )

    def test_properties_used_in_filter_with_actions(self):
        action = Action.objects.create(team=self.team)
        ActionStep.objects.create(
            event="$autocapture", action=action, url="https://example.com/donate", url_matching=ActionStep.EXACT,
        )
        ActionStep.objects.create(
            action=action,
            event="$autocapture",
            tag_name="button",
            text="Pay $10",
            properties=[{"key": "$browser", "value": "Chrome", "type": "person"}],
        )

        filter = Filter(data={"actions": [{"id": action.id, "math": "dau"}]})
        self.assertEqual(
            ColumnOptimizer(filter, self.team.id).properties_used_in_filter,
            {("$current_url", "event"), ("$browser", "person")},
        )

    def test_materialized_columns_checks(self):
        optimizer = lambda: ColumnOptimizer(FILTER_WITH_PROPERTIES, self.team.id)

        self.assertEqual(optimizer().materialized_event_columns_to_query, [])
        self.assertEqual(optimizer().should_query_event_properties_column, True)

        materialize("events", "event_prop")

        self.assertEqual(optimizer().materialized_event_columns_to_query, ["mat_event_prop"])
        self.assertEqual(optimizer().should_query_event_properties_column, False)
