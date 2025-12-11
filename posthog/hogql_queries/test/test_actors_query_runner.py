from datetime import UTC, datetime
from typing import cast

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from posthog.schema import (
    ActorsQuery,
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
    ChartDisplayType,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FunnelsActorsQuery,
    FunnelsQuery,
    HogQLPropertyFilter,
    HogQLQuery,
    HogQLQueryModifiers,
    InsightActorsQuery,
    IntervalType,
    LifecycleQuery,
    PersonPropertyFilter,
    PersonsArgMaxVersion,
    PersonsOnEventsMode,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.visitor import clear_locations

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models.group.util import create_group
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.models.utils import UUIDT
from posthog.test.test_utils import create_group_type_mapping_without_created_at


class TestActorsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None
    random_uuid: str

    def _create_random_persons(self) -> str:
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        for index in range(10):
            _create_person(
                properties={
                    "email": f"jacob{index}@{random_uuid}.posthog.com",
                    "name": f"Mr Jacob {random_uuid}",
                    "random_uuid": random_uuid,
                    "index": index,
                },
                team=self.team,
                distinct_ids=[f"id-{random_uuid}-{index}"],
                is_identified=True,
            )
            _create_event(
                distinct_id=f"id-{random_uuid}-{index}",
                event=f"clicky-{index}",
                team=self.team,
            )

        flush_persons_and_events()
        return random_uuid

    def _create_runner(self, query: ActorsQuery) -> ActorsQueryRunner:
        return ActorsQueryRunner(team=self.team, query=query)

    def setUp(self):
        super().setUp()

    def test_default_persons_query(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery())

        query = runner.to_query()
        query = cast(ast.SelectQuery, clear_locations(query))
        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["id"]),
                ast.Field(chain=["id"]),
                ast.Constant(value=1),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            where=None,
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["id"]), order="ASC")],
        )
        query.settings = None
        assert query == expected
        response = runner.calculate()
        assert len(response.results) == 10

        assert set(response.results[0][0].keys()) == {"id", "created_at", "distinct_ids", "properties", "is_identified"}
        assert response.results[0][0].get("properties").get("random_uuid") == self.random_uuid
        assert len(response.results[0][0].get("distinct_ids")) > 0

    def test_persons_query_properties(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(
            ActorsQuery(
                properties=[
                    PersonPropertyFilter(
                        key="random_uuid",
                        value=self.random_uuid,
                        operator=PropertyOperator.EXACT,
                    ),
                    HogQLPropertyFilter(key="toInt(properties.index) > 5"),
                ]
            )
        )
        self.assertEqual(len(runner.calculate().results), 4)

    def test_persons_query_fixed_properties(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(
            ActorsQuery(
                fixedProperties=[
                    PersonPropertyFilter(
                        key="random_uuid",
                        value=self.random_uuid,
                        operator=PropertyOperator.EXACT,
                    ),
                    HogQLPropertyFilter(key="toInt(properties.index) < 2"),
                ]
            )
        )
        self.assertEqual(len(runner.calculate().results), 2)

    def test_persons_query_search_email(self):
        self.random_uuid = self._create_random_persons()
        self._create_random_persons()
        runner = self._create_runner(ActorsQuery(search=f"jacob4@{self.random_uuid}.posthog"))
        self.assertEqual(len(runner.calculate().results), 1)
        runner = self._create_runner(ActorsQuery(search=f"JACOB4@{self.random_uuid}.posthog"))
        self.assertEqual(len(runner.calculate().results), 1)

    def test_persons_query_search_name(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(search=f"Mr Jacob {self.random_uuid}"))
        self.assertEqual(len(runner.calculate().results), 10)
        runner = self._create_runner(ActorsQuery(search=f"MR JACOB {self.random_uuid}"))
        self.assertEqual(len(runner.calculate().results), 10)

    def test_persons_query_search_distinct_id(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(search=f"id-{self.random_uuid}-9"))
        self.assertEqual(len(runner.calculate().results), 1)
        runner = self._create_runner(ActorsQuery(search=f"id-{self.random_uuid}-9"))
        self.assertEqual(len(runner.calculate().results), 1)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_persons_query_search_snapshot(self):
        runner = self._create_runner(ActorsQuery(search="SEARCHSTRING"))
        assert pretty_print_in_tests(runner.to_hogql(), self.team.pk) == self.snapshot

    def test_persons_query_aggregation_select_having(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(select=["properties.name", "count()"]))
        results = runner.calculate().results
        self.assertEqual(results, [[f"Mr Jacob {self.random_uuid}", 10]])

    def test_persons_query_order_by(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(select=["properties.email"], orderBy=["properties.email DESC"]))
        results = runner.calculate().results
        self.assertEqual(results[0], [f"jacob9@{self.random_uuid}.posthog.com"])

    def test_persons_query_with_insight_actors_source_order_by_last_seen(self):
        _create_person(
            properties={
                "email": f"first@posthog.com",
                "name": "Mr Jump the Gun",
            },
            team=self.team,
            distinct_ids=["jump-the-gun"],
            is_identified=True,
        )
        _create_event(
            distinct_id="jump-the-gun",
            event=f"$pageview",
            team=self.team,
        )
        self.random_uuid = self._create_random_persons()
        _create_person(
            properties={
                "email": "last@posthog.com",
                "name": "Mr Sleepy",
            },
            team=self.team,
            distinct_ids=["sleepy"],
            is_identified=True,
        )
        _create_event(
            distinct_id="sleepy",
            event=f"$pageview",
            team=self.team,
        )
        flush_persons_and_events()

        for direction, expected_email in [("DESC", "last@posthog.com"), ("ASC", "first@posthog.com")]:
            with self.subTest(direction):
                # Create ActorsQuery with InsightActorsQuery source, similar to PowerUsersTable
                query = ActorsQuery(
                    select=["properties.email", "event_count", "last_seen"],
                    source=InsightActorsQuery(
                        source=TrendsQuery(
                            series=[EventsNode(event="$pageview")],
                            dateRange=DateRange(date_from="-30d"),
                            interval=IntervalType.DAY,
                            trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_TABLE),
                        ),
                        series=0,
                    ),
                    orderBy=[f"last_seen {direction}"],
                )

                runner = self._create_runner(query)
                results = runner.calculate().results
                self.assertEqual(results[0][0], expected_email)

    def test_persons_query_order_by_with_aliases(self):
        # We use the first column by default as an order key. It used to cause "error redefining alias" errors.
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(select=["properties.email as email"]))
        results = runner.calculate().results
        self.assertEqual(results[0], [f"jacob0@{self.random_uuid}.posthog.com"])

    def test_persons_query_order_by_person_display_name(self):
        _create_person(
            properties={"email": "tom@posthog.com"},
            distinct_ids=["2", "some-random-uid"],
            team=self.team,
        )
        _create_person(
            properties={"email": "arthur@posthog.com"},
            distinct_ids=["7", "another-random-uid"],
            team=self.team,
        )
        _create_person(
            properties={"email": "chris@posthog.com"},
            distinct_ids=["3", "yet-another-random-uid"],
            team=self.team,
        )
        flush_persons_and_events()
        test_cases = [
            (
                "ascending",
                ["person_display_name -- Person ASC"],
                ["arthur@posthog.com", "chris@posthog.com", "tom@posthog.com"],
            ),
            (
                "descending",
                ["person_display_name -- Person DESC"],
                ["tom@posthog.com", "chris@posthog.com", "arthur@posthog.com"],
            ),
            ("no ordering", [], ["tom@posthog.com", "arthur@posthog.com", "chris@posthog.com"]),
        ]
        for msg, order_by, expected in test_cases:
            with self.subTest(msg):
                runner = self._create_runner(ActorsQuery(select=["person_display_name -- Person"], orderBy=order_by))
                results = runner.calculate().results
                response_order = [person[0]["display_name"] for person in results]
                self.assertEqual(response_order, expected)

    def test_persons_query_order_by_person_display_name_when_column_is_not_selected(self):
        _create_person(
            properties={"email": "tom@posthog.com", "name": "Tom"},
            distinct_ids=["2", "some-random-uid"],
            team=self.team,
        )
        _create_person(
            properties={"email": "arthur@posthog.com", "name": "Arthur"},
            distinct_ids=["7", "another-random-uid"],
            team=self.team,
        )
        _create_person(
            properties={"email": "chris@posthog.com", "name": "Chris"},
            distinct_ids=["3", "yet-another-random-uid"],
            team=self.team,
        )
        flush_persons_and_events()
        test_cases = [
            (
                "ascending",
                ["person_display_name -- Person ASC"],
                ["Arthur", "Chris", "Tom"],
            ),
            (
                "descending",
                ["person_display_name -- Person DESC"],
                ["Tom", "Chris", "Arthur"],
            ),
            ("no ordering", [], ["Tom", "Arthur", "Chris"]),
        ]
        for msg, order_by, expected in test_cases:
            with self.subTest(msg):
                runner = self._create_runner(ActorsQuery(select=["properties.name"], orderBy=order_by))
                results = runner.calculate().results
                response_order = [person[0] for person in results]
                self.assertEqual(response_order, expected)

    def test_persons_query_limit(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(
            ActorsQuery(select=["properties.email"], orderBy=["properties.email DESC"], limit=1)
        )
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob9@{self.random_uuid}.posthog.com"]])
        self.assertEqual(response.hasMore, True)

        runner = self._create_runner(
            ActorsQuery(
                select=["properties.email"],
                orderBy=["properties.email DESC"],
                limit=1,
                offset=2,
            )
        )
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob7@{self.random_uuid}.posthog.com"]])
        self.assertEqual(response.hasMore, True)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_source_hogql_query_poe_on(self):
        self.random_uuid = self._create_random_persons()
        source_query = HogQLQuery(query="SELECT distinct person_id FROM events WHERE event='clicky-4'")
        query = ActorsQuery(
            select=["properties.email"],
            orderBy=["properties.email DESC"],
            source=source_query,
        )
        runner = self._create_runner(query)
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob4@{self.random_uuid}.posthog.com"]])

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_source_hogql_query_poe_off(self):
        self.random_uuid = self._create_random_persons()
        source_query = HogQLQuery(query="SELECT distinct person_id FROM events WHERE event='clicky-4'")
        query = ActorsQuery(
            select=["properties.email"],
            orderBy=["properties.email DESC"],
            source=source_query,
        )
        runner = self._create_runner(query)
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob4@{self.random_uuid}.posthog.com"]])

    def test_source_lifecycle_query(self):
        with freeze_time("2021-01-01T12:00:00Z"):
            self.random_uuid = self._create_random_persons()
        with freeze_time("2021-01-03T12:00:00Z"):
            source_query = LifecycleQuery(
                series=[EventsNode(event="clicky-4")],
                properties=[
                    PersonPropertyFilter(
                        key="random_uuid",
                        value=self.random_uuid,
                        operator=PropertyOperator.EXACT,
                    )
                ],
                interval=IntervalType.DAY,
                dateRange=DateRange(date_from="-7d"),
            )
            query = ActorsQuery(
                select=["properties.email"],
                orderBy=["properties.email DESC"],
                source=InsightActorsQuery(source=source_query),
            )
            runner = self._create_runner(query)
            response = runner.calculate()
            self.assertEqual(response.results, [[f"jacob4@{self.random_uuid}.posthog.com"]])

    def test_persons_query_grouping(self):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        _create_person(
            properties={
                "email": f"jacob0@{random_uuid}.posthog.com",
                "name": f"Mr Jacob {random_uuid}",
                "random_uuid": random_uuid,
                "index": 0,
            },
            team=self.team,
            distinct_ids=[f"id-{random_uuid}-0", f"id-{random_uuid}-1"],
            is_identified=True,
        )
        _create_event(
            distinct_id=f"id-{random_uuid}-0",
            event=f"clicky-0",
            team=self.team,
        )
        _create_event(
            distinct_id=f"id-{random_uuid}-1",
            event=f"clicky-9",
            team=self.team,
        )
        flush_persons_and_events()
        runner = self._create_runner(ActorsQuery(search="posthog.com"))

        response = runner.calculate()
        # Should show a single person despite multiple distinct_ids
        self.assertEqual(len(response.results), 1)

    def test_actors_query_for_first_matching_event(self):
        _create_person(
            team=self.team,
            distinct_ids=["p1"],
            properties={},
        )
        _create_person(
            team=self.team,
            distinct_ids=["p2"],
            properties={},
        )
        _create_person(
            team=self.team,
            distinct_ids=["p3"],
            properties={},
        )
        _create_person(
            team=self.team,
            distinct_ids=["p4"],
            properties={},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-02T12:00:00Z",
            properties={"$browser": "Chrome", "breakdown_prop": 3},
        )

        for i in range(1, 5):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-08T12:00:00Z",
                properties={"$browser": "Chrome", "breakdown_prop": f"{i if i == 3 else 1}"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-09T12:00:00Z",
                properties={"$browser": "Chrome", "breakdown_prop": f"{i if i == 3 else 1}"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-10T12:00:00Z",
                properties={"$browser": "Firefox", "breakdown_prop": f"{i if i == 3 else 1}"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"$browser": "Firefox", "breakdown_prop": f"{i if i == 3 else 1}"},
            )

        flush_persons_and_events()

        source_query = TrendsQuery(
            dateRange=DateRange(date_from="2020-01-08", date_to="2020-01-11"),
            interval=IntervalType.DAY,
            series=[
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_MATCHING_EVENT_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Firefox")],
                )
            ],
            breakdownFilter=BreakdownFilter(breakdown_type=BreakdownType.EVENT, breakdown="breakdown_prop"),
        )

        runner = self._create_runner(
            ActorsQuery(source=InsightActorsQuery(source=source_query, day="2020-01-10T00:00:00Z", breakdown="3"))
        )

        response = runner.calculate()

        assert len(response.results) == 1

    def test_actors_query_url_normalization(self):
        _create_person(
            team=self.team,
            distinct_ids=["p1"],
            properties={},
        )
        _create_person(
            team=self.team,
            distinct_ids=["p2"],
            properties={},
        )

        for i in range(1, 4):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-08T12:00:00Z",
                properties={"$browser": "Chrome", "current_url": "https://example.com/"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-09T12:00:00Z",
                properties={"$browser": "Chrome", "current_url": "https://example.com/"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-10T12:00:00Z",
                properties={"$browser": "Firefox", "current_url": "https://example.com/"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"p{i}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"$browser": "Firefox", "current_url": "https://example.com/"},
            )

        flush_persons_and_events()

        source_query = TrendsQuery(
            dateRange=DateRange(date_from="2020-01-08", date_to="2020-01-11"),
            interval=IntervalType.DAY,
            series=[
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.FIRST_MATCHING_EVENT_FOR_USER,
                    properties=[EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Firefox")],
                )
            ],
            breakdownFilter=BreakdownFilter(
                breakdown_type=BreakdownType.EVENT, breakdown="current_url", breakdown_normalize_url=True
            ),
        )

        runner = self._create_runner(
            ActorsQuery(
                source=InsightActorsQuery(
                    source=source_query, day="2020-01-10T00:00:00Z", breakdown="https://example.com"
                )
            )
        )

        response = runner.calculate()

        assert len(response.results) == 3

    def test_default_group_actors_query(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org1",
            properties={"name": "org1.inc"},
            sync=True,
        )

        _create_person(
            team=self.team,
            distinct_ids=["user1"],
            properties={},
        )

        _create_event(
            team=self.team,
            event="pageview",
            distinct_id="user1",
            properties={"$group_0": "org1"},
            timestamp="2023-01-01T12:00:00Z",
        )

        _create_person(
            team=self.team,
            distinct_ids=["user2"],
            properties={},
        )

        _create_event(
            team=self.team,
            event="pageview",
            distinct_id="user",
            properties={"$group_0": "org2"},
            timestamp="2023-01-01T12:30:00Z",
        )

        flush_persons_and_events()

        runner = self._create_runner(
            ActorsQuery(
                select=["actor"],
                source=InsightActorsQuery(
                    source=TrendsQuery(
                        dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-01"),
                        interval=IntervalType.DAY,
                        series=[EventsNode(event="pageview", math="unique_group", math_group_type_index=0)],
                    ),
                    series=0,
                    day="2023-01-01T12:00:00Z",
                ),
            )
        )
        response = runner.calculate()

        assert len(response.results) == 2
        group = response.results[0][0]
        assert group["id"] == "org1"
        assert group["properties"]["name"] == "org1.inc"
        assert set(group.keys()) == {
            "id",
            "group_key",
            "group_type_index",
            "created_at",
            "properties",
            "group_properties",
            "type",
        }

        group = response.results[1][0]
        assert group["id"] == "org2"
        assert set(group.keys()) == {"id", "group_type_index"}

    @patch("posthog.hogql_queries.insights.paginators.execute_hogql_query", wraps=execute_hogql_query)
    def test_funnel_source_with_poe_mode(self, spy_execute_hogql_query):
        self.team.modifiers = {
            **(self.team.modifiers or {}),
            "personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
        }
        self.team.save()

        self.random_uuid = self._create_random_persons()
        funnel_query = FunnelsQuery(
            series=[
                EventsNode(event="clicky-1"),
                EventsNode(event="clicky-2"),
            ],
            modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
        )

        runner = self._create_runner(ActorsQuery(source=FunnelsActorsQuery(funnelStep=1, source=funnel_query)))

        runner.calculate()

        # Verify that execute_hogql_query was called with the correct modifiers
        called_modifiers: HogQLQueryModifiers = spy_execute_hogql_query.call_args[1]["modifiers"]
        self.assertEqual(called_modifiers.personsOnEventsMode, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED)

    def test_person_display_name_default(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email", "id_anon"],
            properties={"email": "user@email.com", "name": "Test User"},
        )
        flush_persons_and_events()
        query = ActorsQuery(select=["person_display_name"])
        runner = self._create_runner(query)
        response = runner.calculate()
        display_names = [row[0]["display_name"] for row in response.results]
        assert set(display_names) == {"user@email.com"}

    def test_person_display_name_custom(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email", "id_anon"],
            properties={"email": "user@email.com", "name": "Test User", "numeric_prop": 123},
        )
        self.team.person_display_name_properties = ["name", "numeric_prop"]
        self.team.save()
        self.team.refresh_from_db()
        flush_persons_and_events()
        PropertyDefinition.objects.create(
            team_id=self.team.pk,
            name="numeric_prop",
            property_type=PropertyType.Numeric,
            is_numerical=True,
            type=PropertyDefinition.Type.PERSON,
        )
        query = ActorsQuery(select=["person_display_name"])
        runner = self._create_runner(query)
        response = runner.calculate()
        display_names = [row[0]["display_name"] for row in response.results]
        assert set(display_names) == {"Test User"}

    def test_person_display_name_fallback(self):
        person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email", "id_anon"],
            properties={"email": "user@email.com", "name": "Test User"},
        )
        self.team.person_display_name_properties = ["nonexistent"]
        self.team.save()
        self.team.refresh_from_db()
        flush_persons_and_events()
        query = ActorsQuery(select=["person_display_name"])
        runner = self._create_runner(query)
        response = runner.calculate()
        display_names = [row[0]["display_name"] for row in response.results]
        assert set(display_names) == {str(person.uuid)}

    def test_person_display_name_with_spaces_in_property_name(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email", "id_anon"],
            properties={"email": "user@email.com", "Property With Spaces": "Test User With Spaces"},
        )
        self.team.person_display_name_properties = ["Property With Spaces"]
        self.team.save()
        self.team.refresh_from_db()
        flush_persons_and_events()
        query = ActorsQuery(select=["person_display_name"])
        runner = self._create_runner(query)
        response = runner.calculate()
        display_names = [row[0]["display_name"] for row in response.results]
        assert set(display_names) == {"Test User With Spaces"}

    def test_select_property_name_with_spaces(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email", "id_anon"],
            properties={"email": "user@email.com", "Property With Spaces": "Test User With Spaces"},
        )
        flush_persons_and_events()
        query = ActorsQuery(select=['properties."Property With Spaces"'])
        runner = self._create_runner(query)

        response = runner.calculate()

        self.assertEqual(response.results[0][0], "Test User With Spaces")

    def test_direct_actors_query_uses_latest_person_data_after_property_deletion(self):
        """Test that direct ActorsQuery uses latest person data and doesn't show deleted properties."""
        # Create a person with email property first
        person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["user_with_email"],
            properties={"email": "test@example.com", "name": "Test User"},
        )
        flush_persons_and_events()

        # Simulate property deletion by directly inserting a newer version in ClickHouse
        # This mimics what happens when a person property is deleted via the API

        # Insert a newer version without the email property (simulating deletion)
        sync_execute(
            """
            INSERT INTO person (id, team_id, properties, is_identified, is_deleted, version, created_at)
            VALUES (%(person_id)s, %(team_id)s, %(properties)s, 1, 0, %(version)s, %(created_at)s)
            """,
            {
                "person_id": str(person.uuid),
                "team_id": self.team.pk,
                "properties": '{"name": "Test User"}',  # email property removed
                "version": 1,  # Newer version
                "created_at": datetime.now(UTC),
            },
        )

        # Test: Query for persons with email containing '@' should return NO results
        # because the latest version doesn't have an email property
        query = ActorsQuery(
            select=["person_display_name -- Person ", "id", "created_at"],
            search="@",  # This searches email property among others
        )
        runner = self._create_runner(query)
        response = runner.calculate()

        # Should return no results because latest version doesn't have email with @
        person_ids_in_results = [row[1] for row in response.results]
        self.assertNotIn(
            str(person.uuid),
            person_ids_in_results,
            "Person with deleted email property should not appear in search results for '@'",
        )

        # Verify that direct ActorsQuery is using PersonsArgMaxVersion.V2
        self.assertEqual(
            runner.modifiers.personsArgMaxVersion,
            PersonsArgMaxVersion.V2,
            "Direct ActorsQuery should use PersonsArgMaxVersion.V2 for latest person data",
        )

    def test_person_strategy_batches_large_actor_sets(self):
        """Verify that PersonStrategy.get_actors batches queries."""
        from posthog.hogql_queries.actor_strategies import PersonStrategy
        from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator

        # Create 5 persons
        person_uuids = []
        for i in range(5):
            person = _create_person(
                properties={"email": f"batch_test_{i}@example.com"},
                team=self.team,
                distinct_ids=[f"batch-test-{UUIDT()}-{i}"],
                is_identified=True,
            )
            person_uuids.append(str(person.uuid))
        flush_persons_and_events()

        query = ActorsQuery()
        paginator = HogQLHasMorePaginator(limit=100, offset=0)
        strategy = PersonStrategy(team=self.team, query=query, paginator=paginator)

        # Temporarily set a small batch size to verify batching works
        with patch.object(PersonStrategy, "BATCH_SIZE", 2):
            result = strategy.get_actors(person_uuids)

        self.assertEqual(len(result), 5)
        for uuid in person_uuids:
            self.assertIn(uuid, result)

    @freeze_time("2023-05-10T15:00:00Z")
    def test_last_seen_for_persons(self):
        # Create person with events at different times
        _create_person(
            properties={"email": "test@example.com"},
            team=self.team,
            distinct_ids=["user123"],
            is_identified=True,
        )

        # Create events at different times
        with freeze_time("2023-05-08T10:00:00Z"):
            _create_event(event="early_event", distinct_id="user123", team=self.team)

        with freeze_time("2023-05-09T14:30:00Z"):
            _create_event(event="late_event", distinct_id="user123", team=self.team)

        flush_persons_and_events()

        # Query with last_seen included
        query = ActorsQuery(select=["person", "id", "last_seen"])
        runner = ActorsQueryRunner(query=query, team=self.team)

        response = runner.calculate()

        self.assertEqual(len(response.results), 2, "One for each event")
        result = response.results[0]

        # Check that last_seen is the timestamp of the latest event
        last_seen_idx = response.columns.index("last_seen")
        last_seen_value = result[last_seen_idx]

        self.assertEqual(str(last_seen_value), "2023-05-09 14:30:00+00:00")

    def test_last_seen_not_calculated_when_not_requested(self):
        _create_person(
            properties={"email": "test@example.com"},
            team=self.team,
            distinct_ids=["user123"],
            is_identified=True,
        )
        _create_event(event="test_event", distinct_id="user123", team=self.team)
        flush_persons_and_events()

        # Query without last_seen
        query = ActorsQuery(select=["person", "id"])
        runner = ActorsQueryRunner(query=query, team=self.team)

        response = runner.calculate()

        # Should not have last_seen column
        self.assertNotIn("last_seen", response.columns)
        # Generated SQL should not contain events table reference
        hogql = runner.to_query()
        printed_query = str(hogql)
        self.assertNotIn("events", printed_query.lower())
