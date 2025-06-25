from typing import cast

import pytest

from posthog.hogql import ast
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.visitor import clear_locations
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.group.util import create_group
from posthog.models.utils import UUIDT
from posthog.schema import (
    ActorsQuery,
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
    EventPropertyFilter,
    PersonPropertyFilter,
    HogQLPropertyFilter,
    PropertyOperator,
    HogQLQuery,
    LifecycleQuery,
    DateRange,
    EventsNode,
    IntervalType,
    InsightActorsQuery,
    TrendsQuery,
    FunnelsQuery,
    HogQLQueryModifiers,
    FunnelsActorsQuery,
    PersonsOnEventsMode,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    flush_persons_and_events,
    _create_event,
)
from freezegun import freeze_time
from django.test import override_settings
from unittest.mock import patch
from posthog.hogql.query import execute_hogql_query
from posthog.models.property_definition import PropertyDefinition, PropertyType


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
        GroupTypeMapping.objects.create(
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
