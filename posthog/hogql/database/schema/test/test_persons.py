from datetime import datetime

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.schema import (
    ActorsQuery,
    CustomChannelCondition,
    CustomChannelField,
    CustomChannelOperator,
    CustomChannelRule,
    DateRange,
    EventsNode,
    FilterLogicalOperator,
    HogQLQueryModifiers,
    InsightActorsQuery,
    PersonsOnEventsMode,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.database.schema.persons import _is_virtual_field_requiring_join
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.models.person.util import create_person


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))  # for persons-inner-where-optimization
class TestPersonOptimization(ClickhouseTestMixin, APIBaseTest):
    """
    Mostly tests for the optimization of pre-filtering before aggregating. See https://github.com/PostHog/posthog/pull/25604
    """

    def setUp(self):
        super().setUp()
        self.first_person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something1"},
            created_at=datetime(2024, 1, 1, 12),
        )
        self.second_person = _create_person(
            team_id=self.team.pk,
            properties={"$some_prop": "ifwematcholdversionsthiswillmatch", "$another_prop": "something2"},
            distinct_ids=["2"],
            version=1,
            created_at=datetime(2024, 1, 1, 13),
        )
        # update second_person with the correct prop
        create_person(
            team_id=self.team.pk,
            uuid=str(self.second_person.uuid),
            properties={"$some_prop": "something", "$another_prop": "something2"},
            created_at=datetime(2024, 1, 1, 13),
            version=2,
        )
        self.third_person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["3"],
            properties={"$some_prop": "not something", "$another_prop": "something3"},
            created_at=datetime(2024, 1, 1, 14),
        )
        # deleted
        self.deleted_person = _create_person(
            team_id=self.team.pk,
            properties={"$some_prop": "ifwematcholdversionsthiswillmatch", "$another_prop": "something2"},
            distinct_ids=["deleted"],
            created_at=datetime(2024, 1, 1, 13),
            version=1,
        )
        create_person(team_id=self.team.pk, uuid=str(self.deleted_person.uuid), version=2, is_deleted=True)
        _create_event(event="$pageview", distinct_id="1", team=self.team)
        _create_event(event="$pageview", distinct_id="2", team=self.team)
        _create_event(event="$pageview", distinct_id="3", team=self.team)
        self.modifiers = create_default_modifiers_for_team(self.team)
        self.modifiers.personsOnEventsMode = PersonsOnEventsMode.DISABLED
        # self.modifiers.optimizeJoinedFilters = True
        # self.modifiers.personsArgMaxVersion = PersonsArgMaxVersion.V1

    @snapshot_clickhouse_queries
    def test_simple_filter(self):
        response = execute_hogql_query(
            parse_select("select id, properties from persons where properties.$some_prop = 'something'"),
            self.team,
            modifiers=self.modifiers,
        )
        assert len(response.results) == 2
        assert response.clickhouse
        self.assertIn("where_optimization", response.clickhouse)
        self.assertNotIn("in(tuple(person.id, person.version)", response.clickhouse)

    @snapshot_clickhouse_queries
    def test_joins_are_left_alone_for_now(self):
        response = execute_hogql_query(
            parse_select("select uuid from events where person.properties.$some_prop = 'something'"),
            self.team,
            modifiers=self.modifiers,
        )
        assert len(response.results) == 2
        assert response.clickhouse
        self.assertIn("in(tuple(person.id, person.version)", response.clickhouse)
        self.assertNotIn("where_optimization", response.clickhouse)

    def test_person_modal_not_optimized_yet(self):
        source_query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            # breakdownFilter=BreakdownFilter(breakdown="$", breakdown_type=BreakdownType.PERSON),
        )
        insight_actors_query = InsightActorsQuery(
            source=source_query,
            day="2024-01-01",
            modifiers=self.modifiers,
        )
        actors_query = ActorsQuery(
            source=insight_actors_query,
            offset=0,
            select=[
                "actor",
                "created_at",
                "event_count",
                # "matched_recordings",
            ],
            orderBy=["event_count DESC"],
            modifiers=self.modifiers,
        )
        query_runner = ActorsQueryRunner(query=actors_query, team=self.team)
        response = execute_hogql_query(query_runner.to_query(), self.team, modifiers=self.modifiers)
        assert response.clickhouse
        self.assertNotIn("where_optimization", response.clickhouse)

    @snapshot_clickhouse_queries
    def test_order_by_limit_transferred(self):
        response = execute_hogql_query(
            parse_select(
                "select id, properties from persons where properties.$some_prop = 'something' ORDER BY created_at DESC LIMIT 2"
            ),
            self.team,
            modifiers=self.modifiers,
        )
        assert len(response.results) == 2
        assert response.clickhouse
        self.assertIn("where_optimization", response.clickhouse)
        self.assertNotIn("in(tuple(person.id, person.version)", response.clickhouse)


class TestPersons(ClickhouseTestMixin, APIBaseTest):
    person_properties = {"$initial_referring_domain": "https://google.com"}
    poe_properties = {"$initial_referring_domain": "https://facebook.com", "$initial_utm_medium": "cpc"}

    channel_type_virt_person_result = "Organic Search"
    channel_type_virt_poe_result = "Paid Social"

    custom_channel_type_rules = [
        CustomChannelRule(
            channel_type="Custom Search",
            id="0",
            combiner=FilterLogicalOperator.OR_,
            items=[
                CustomChannelCondition(
                    id="0",
                    key=CustomChannelField.REFERRING_DOMAIN,
                    op=CustomChannelOperator.EXACT,
                    value="https://google.com",
                )
            ],
        ),
        CustomChannelRule(
            channel_type="Custom Social",
            id="0",
            combiner=FilterLogicalOperator.OR_,
            items=[
                CustomChannelCondition(
                    id="0",
                    key=CustomChannelField.REFERRING_DOMAIN,
                    op=CustomChannelOperator.EXACT,
                    value="https://facebook.com",
                )
            ],
        ),
    ]

    def setUp(self):
        super().setUp()
        self.person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties=self.person_properties,
            created_at=datetime(2025, 5, 28, 12),
        )
        _create_event(
            distinct_id="1",
            event="$pageview",
            person_properties=self.poe_properties,
            timestamp=datetime(2025, 5, 28, 12),
            team=self.team,
        )
        flush_persons_and_events()

    def test_virtual_person_properties(self):
        response = execute_hogql_query(
            parse_select("select $virt_initial_channel_type from persons where id = {person_id}"),
            self.team,
            placeholders={"person_id": ast.Constant(value=self.person.uuid)},
        )
        assert len(response.results) == 1
        assert response.results[0][0] == self.channel_type_virt_person_result

    def test_virtual_event_person_properties(self):
        response = execute_hogql_query(
            parse_select("select person.$virt_initial_channel_type from events where person.id = {person_id}"),
            self.team,
            placeholders={"person_id": ast.Constant(value=self.person.uuid)},
        )
        assert len(response.results) == 1
        assert response.results[0][0] == self.channel_type_virt_person_result

    def test_virtual_event_poe_properties(self):
        response = execute_hogql_query(
            parse_select("select events.poe.$virt_initial_channel_type from events where person.id = {person_id}"),
            self.team,
            placeholders={"person_id": ast.Constant(value=self.person.uuid)},
        )
        assert len(response.results) == 1
        assert response.results[0][0] == self.channel_type_virt_poe_result

    def test_virtual_event_pdi_properties(self):
        response = execute_hogql_query(
            parse_select(
                "select events.pdi.person.$virt_initial_channel_type from events where person.id = {person_id}"
            ),
            self.team,
            placeholders={"person_id": ast.Constant(value=self.person.uuid)},
        )
        assert len(response.results) == 1
        assert response.results[0][0] == self.channel_type_virt_person_result

    @parameterized.expand([e.value for e in PersonsOnEventsMode])
    def test_channel_type_virt_property_in_trend(self, mode):
        expected = (
            self.channel_type_virt_person_result
            if mode in [PersonsOnEventsMode.DISABLED, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED]
            else self.channel_type_virt_poe_result
        )
        query = TrendsQuery(
            **{
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "name": "$pageview", "event": "$pageview", "math": "total"}],
                "trendsFilter": {},
                "breakdownFilter": {"breakdowns": [{"property": "$virt_initial_channel_type", "type": "person"}]},
            },
            dateRange=DateRange(date_from="all", date_to=None),
            modifiers=HogQLQueryModifiers(personsOnEventsMode=mode),
        )
        tqr = TrendsQueryRunner(team=self.team, query=query)
        results = tqr.calculate().results
        assert results[0]["breakdown_value"] == [expected]

    @parameterized.expand([e.value for e in PersonsOnEventsMode])
    def test_channel_type_virt_property_in_trend_with_custom_rules(self, mode):
        expected = (
            "Custom Search"
            if mode in [PersonsOnEventsMode.DISABLED, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED]
            else "Custom Social"
        )
        query = TrendsQuery(
            **{
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "name": "$pageview", "event": "$pageview", "math": "total"}],
                "trendsFilter": {},
                "breakdownFilter": {"breakdowns": [{"property": "$virt_initial_channel_type", "type": "person"}]},
            },
            dateRange=DateRange(date_from="all", date_to=None),
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=mode, customChannelTypeRules=self.custom_channel_type_rules
            ),
        )
        tqr = TrendsQueryRunner(team=self.team, query=query)
        # test that it doesn't throw
        results = tqr.calculate().results
        assert results[0]["breakdown_value"] == [expected]


class TestVirtualFieldDetection(APIBaseTest):
    @parameterized.expand(
        [
            # Cases that should return True (require joins - revenue analytics fields)
            ("virt_mrr_simple", ast.Field(chain=["$virt_mrr"]), True),
            ("virt_revenue_simple", ast.Field(chain=["$virt_revenue"]), True),
            ("virt_mrr_in_function_sum", ast.Call(name="sum", args=[ast.Field(chain=["$virt_mrr"])]), True),
            ("virt_revenue_in_function_count", ast.Call(name="count", args=[ast.Field(chain=["$virt_revenue"])]), True),
            (
                "virt_mrr_in_comparison",
                ast.CompareOperation(
                    left=ast.Field(chain=["$virt_mrr"]), op=ast.CompareOperationOp.Gt, right=ast.Constant(value=100)
                ),
                True,
            ),
            ("virt_revenue_in_alias", ast.Alias(alias="revenue", expr=ast.Field(chain=["$virt_revenue"])), True),
            (
                "virt_mrr_in_arithmetic",
                ast.ArithmeticOperation(
                    left=ast.Field(chain=["$virt_mrr"]), op=ast.ArithmeticOperationOp.Add, right=ast.Constant(value=10)
                ),
                True,
            ),
            # Cases that should return False (no join required)
            ("regular_field_created_at", ast.Field(chain=["created_at"]), False),
            ("regular_field_id", ast.Field(chain=["id"]), False),
            ("regular_field_properties", ast.Field(chain=["properties"]), False),
            ("inline_virtual_channel_type", ast.Field(chain=["$virt_initial_channel_type"]), False),
            ("inline_virtual_domain_type", ast.Field(chain=["$virt_initial_referring_domain_type"]), False),
            ("unknown_virtual_field", ast.Field(chain=["$virt_unknown"]), False),
            ("non_virtual_field_with_dollar", ast.Field(chain=["$session_id"]), False),
            ("empty_chain", ast.Field(chain=[]), False),
            ("regular_function_without_virtual", ast.Call(name="sum", args=[ast.Field(chain=["id"])]), False),
            (
                "comparison_without_virtual",
                ast.CompareOperation(
                    left=ast.Field(chain=["created_at"]),
                    op=ast.CompareOperationOp.Gt,
                    right=ast.Constant(value="2024-01-01"),
                ),
                False,
            ),
            # Edge cases
            ("constant_value", ast.Constant(value=42), False),
            (
                "mixed_expression_with_virtual",
                ast.CompareOperation(
                    left=ast.Field(chain=["$virt_mrr"]),
                    op=ast.CompareOperationOp.GtEq,
                    right=ast.Constant(value=1000),
                ),
                True,
            ),
            (
                "nested_function_with_virtual",
                ast.Call(name="round", args=[ast.Call(name="sum", args=[ast.Field(chain=["$virt_revenue"])])]),
                True,
            ),
            (
                "complex_nested_no_virtual",
                ast.Call(name="round", args=[ast.Call(name="sum", args=[ast.Field(chain=["id"])])]),
                False,
            ),
        ]
    )
    def test_is_virtual_field_requiring_join(self, name: str, expr: ast.Expr, expected: bool):
        result = _is_virtual_field_requiring_join(expr)
        self.assertEqual(result, expected, f"Failed for test case: {name}")

    def test_complex_nested_expression(self):
        complex_expr = ast.CompareOperation(
            left=ast.ArithmeticOperation(
                left=ast.Field(chain=["$virt_mrr"]), op=ast.ArithmeticOperationOp.Add, right=ast.Constant(value=100)
            ),
            op=ast.CompareOperationOp.Gt,
            right=ast.ArithmeticOperation(
                left=ast.Field(chain=["created_at"]),
                op=ast.ArithmeticOperationOp.Sub,
                right=ast.Constant(value=1000),
            ),
        )

        result = _is_virtual_field_requiring_join(complex_expr)

        self.assertTrue(result, "Complex expression with virtual field should return True")

    def test_multiple_virtual_fields(self):
        expr = ast.ArithmeticOperation(
            left=ast.Field(chain=["$virt_mrr"]),
            op=ast.ArithmeticOperationOp.Add,
            right=ast.Field(chain=["$virt_revenue"]),
        )

        result = _is_virtual_field_requiring_join(expr)

        self.assertTrue(result, "Expression with multiple virtual fields should return True")

    def test_no_exception_on_malformed_ast(self):
        class MockASTNode:
            def __init__(self):
                self.unexpected_attr = "test"

        mock_node = MockASTNode()

        result = _is_virtual_field_requiring_join(mock_node)  # type: ignore
        self.assertFalse(result, "Malformed AST should return False without exception")
