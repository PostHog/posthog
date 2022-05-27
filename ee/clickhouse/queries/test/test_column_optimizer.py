from ee.clickhouse.materialized_columns import materialize
from ee.clickhouse.queries.column_optimizer import EnterpriseColumnOptimizer
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models import Action, ActionStep
from posthog.models.filters import Filter
from posthog.test.base import APIBaseTest

PROPERTIES_OF_ALL_TYPES = [
    {"key": "event_prop", "value": ["foo", "bar"], "type": "event"},
    {"key": "person_prop", "value": "efg", "type": "person"},
    {"key": "id", "value": 1, "type": "cohort"},
    {"key": "tag_name", "value": ["label"], "operator": "exact", "type": "element"},
    {"key": "group_prop", "value": ["value"], "operator": "exact", "type": "group", "group_type_index": 2},
]

BASE_FILTER = Filter({"events": [{"id": "$pageview", "type": "events", "order": 0}]})
FILTER_WITH_PROPERTIES = BASE_FILTER.with_data({"properties": PROPERTIES_OF_ALL_TYPES})
FILTER_WITH_GROUPS = BASE_FILTER.with_data({"properties": {"type": "AND", "values": PROPERTIES_OF_ALL_TYPES}})


class TestColumnOptimizer(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.test_account_filters = PROPERTIES_OF_ALL_TYPES
        self.team.save()

    def test_properties_used_in_filter(self):
        properties_used_in_filter = lambda filter: EnterpriseColumnOptimizer(
            filter, self.team.id
        ).properties_used_in_filter

        self.assertEqual(properties_used_in_filter(BASE_FILTER), {})
        self.assertEqual(
            properties_used_in_filter(FILTER_WITH_PROPERTIES),
            {
                ("event_prop", "event", None): 1,
                ("person_prop", "person", None): 1,
                ("id", "cohort", None): 1,
                ("tag_name", "element", None): 1,
                ("group_prop", "group", 2): 1,
            },
        )
        self.assertEqual(
            properties_used_in_filter(FILTER_WITH_GROUPS),
            {
                ("event_prop", "event", None): 1,
                ("person_prop", "person", None): 1,
                ("id", "cohort", None): 1,
                ("tag_name", "element", None): 1,
                ("group_prop", "group", 2): 1,
            },
        )

        # Breakdown cases
        filter = BASE_FILTER.with_data({"breakdown": "some_prop", "breakdown_type": "person"})
        self.assertEqual(properties_used_in_filter(filter), {("some_prop", "person", None): 1})

        filter = BASE_FILTER.with_data({"breakdown": "some_prop", "breakdown_type": "event"})
        self.assertEqual(properties_used_in_filter(filter), {("some_prop", "event", None): 1})

        filter = BASE_FILTER.with_data({"breakdown": [11], "breakdown_type": "cohort"})
        self.assertEqual(properties_used_in_filter(filter), {})

        filter = BASE_FILTER.with_data(
            {"breakdown": "some_prop", "breakdown_type": "group", "breakdown_group_type_index": 1}
        )
        self.assertEqual(properties_used_in_filter(filter), {("some_prop", "group", 1): 1})

        # Funnel Correlation cases
        filter = BASE_FILTER.with_data(
            {"funnel_correlation_type": "events", "funnel_correlation_names": ["random_column"]}
        )
        self.assertEqual(properties_used_in_filter(filter), {})

        filter = BASE_FILTER.with_data(
            {"funnel_correlation_type": "properties", "funnel_correlation_names": ["random_column", "$browser"]}
        )
        self.assertEqual(
            properties_used_in_filter(filter), {("random_column", "person", None): 1, ("$browser", "person", None): 1}
        )

        filter = BASE_FILTER.with_data(
            {
                "funnel_correlation_type": "properties",
                "funnel_correlation_names": ["random_column", "$browser"],
                "aggregation_group_type_index": 2,
            }
        )
        self.assertEqual(
            properties_used_in_filter(filter), {("random_column", "group", 2): 1, ("$browser", "group", 2): 1}
        )

        filter = BASE_FILTER.with_data({"funnel_correlation_type": "properties"})
        self.assertEqual(properties_used_in_filter(filter), {})

        filter = Filter(
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "math": "sum",
                        "math_property": "numeric_prop",
                        "properties": PROPERTIES_OF_ALL_TYPES,
                    }
                ]
            }
        )
        self.assertEqual(
            properties_used_in_filter(filter),
            {
                ("numeric_prop", "event", None): 1,
                ("event_prop", "event", None): 1,
                ("person_prop", "person", None): 1,
                ("id", "cohort", None): 1,
                ("tag_name", "element", None): 1,
                ("group_prop", "group", 2): 1,
            },
        )

        filter = Filter(
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "math": "unique_group",
                        "math_group_type_index": 1,
                    }
                ]
            }
        )
        self.assertEqual(
            properties_used_in_filter(filter), {("$group_1", "event", None): 1,},
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
            EnterpriseColumnOptimizer(filter, self.team.id).properties_used_in_filter,
            {("$current_url", "event", None): 1, ("$browser", "person", None): 1},
        )

        filter = BASE_FILTER.with_data({"exclusions": [{"id": action.id, "type": "actions"}]})
        self.assertEqual(
            EnterpriseColumnOptimizer(filter, self.team.id).properties_used_in_filter,
            {("$current_url", "event", None): 1, ("$browser", "person", None): 1},
        )

    def test_materialized_columns_checks(self):
        optimizer = lambda: EnterpriseColumnOptimizer(FILTER_WITH_PROPERTIES, self.team.id)
        optimizer_groups = lambda: EnterpriseColumnOptimizer(FILTER_WITH_GROUPS, self.team.id)

        self.assertEqual(optimizer().event_columns_to_query, {"properties"})
        self.assertEqual(optimizer().person_columns_to_query, {"properties"})
        self.assertEqual(optimizer_groups().event_columns_to_query, {"properties"})
        self.assertEqual(optimizer_groups().person_columns_to_query, {"properties"})

        materialize("events", "event_prop")
        materialize("person", "person_prop")

        self.assertEqual(optimizer().event_columns_to_query, {"mat_event_prop"})
        self.assertEqual(optimizer().person_columns_to_query, {"pmat_person_prop"})
        self.assertEqual(optimizer_groups().event_columns_to_query, {"mat_event_prop"})
        self.assertEqual(optimizer_groups().person_columns_to_query, {"pmat_person_prop"})

    def test_should_query_element_chain_column(self):
        should_query_elements_chain_column = lambda filter: EnterpriseColumnOptimizer(
            filter, self.team.id
        ).should_query_elements_chain_column

        self.assertEqual(should_query_elements_chain_column(BASE_FILTER), False)
        self.assertEqual(should_query_elements_chain_column(FILTER_WITH_PROPERTIES), True)
        self.assertEqual(should_query_elements_chain_column(FILTER_WITH_GROUPS), True)

        filter = Filter(
            data={"events": [{"id": "$pageview", "type": "events", "order": 0, "properties": PROPERTIES_OF_ALL_TYPES,}]}
        )
        self.assertEqual(should_query_elements_chain_column(filter), True)

    def test_should_query_element_chain_column_with_actions(self):
        action = Action.objects.create(team=self.team)
        step1 = ActionStep.objects.create(
            event="$autocapture", action=action, url="https://example.com/donate", url_matching=ActionStep.EXACT,
        )

        filter = Filter(data={"actions": [{"id": action.id, "math": "dau"}]})
        self.assertEqual(
            EnterpriseColumnOptimizer(filter, self.team.id).should_query_elements_chain_column, False,
        )

        ActionStep.objects.create(
            action=action, event="$autocapture", tag_name="button", text="Pay $10",
        )

        self.assertEqual(
            EnterpriseColumnOptimizer(filter, self.team.id).should_query_elements_chain_column, True,
        )

        filter = BASE_FILTER.with_data({"exclusions": [{"id": action.id, "type": "actions"}]})
        self.assertEqual(
            EnterpriseColumnOptimizer(filter, self.team.id).should_query_elements_chain_column, True,
        )

    def test_group_types_to_query(self):
        group_types_to_query = lambda filter: EnterpriseColumnOptimizer(filter, self.team.id).group_types_to_query

        self.assertEqual(group_types_to_query(BASE_FILTER), set())
        self.assertEqual(group_types_to_query(FILTER_WITH_PROPERTIES), {2})
        self.assertEqual(group_types_to_query(FILTER_WITH_GROUPS), {2})
