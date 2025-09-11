from datetime import datetime
from typing import Any, cast

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_different_timezones,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from posthog.schema import (
    CachedEventsQueryResponse,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    EventsQuery,
    HogQLQueryModifiers,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp

from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models import Element, Person, Team
from posthog.models.organization import Organization


class TestEventsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_events(self, data: list[tuple[str, str, Any]], event="$pageview"):
        person_result = []
        distinct_ids_handled = set()
        for distinct_id, timestamp, event_properties in data:
            with freeze_time(timestamp):
                if distinct_id not in distinct_ids_handled:
                    person_result.append(
                        _create_person(
                            team_id=self.team.pk,
                            distinct_ids=[distinct_id],
                            properties={
                                "name": distinct_id,
                            },
                        )
                    )
                    distinct_ids_handled.add(distinct_id)
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties=event_properties,
                )
        return person_result

    def _create_boolean_field_test_events(self):
        self._create_events(
            data=[
                (
                    "p_true",
                    "2020-01-11T12:00:01Z",
                    {"boolean_field": True},
                ),
                (
                    "p_false",
                    "2020-01-11T12:00:02Z",
                    {"boolean_field": False},
                ),
                (
                    "p_notset",
                    "2020-01-11T12:00:04Z",
                    {},
                ),
                (
                    "p_null",
                    "2020-01-11T12:00:04Z",
                    {"boolean_field": None},
                ),
            ]
        )

    def _run_boolean_field_query(self, filter: EventPropertyFilter):
        with freeze_time("2020-01-11T12:01:00"):
            query = EventsQuery(
                after="-24h",
                event="$pageview",
                kind="EventsQuery",
                orderBy=["timestamp ASC"],
                select=["*"],
                properties=[filter],
            )

            runner = EventsQueryRunner(query=query, team=self.team)
            response = runner.run()
            assert isinstance(response, CachedEventsQueryResponse)
            results = response.results
            return results

    def test_is_not_set_boolean(self):
        # see https://github.com/PostHog/posthog/issues/18030
        self._create_boolean_field_test_events()
        results = self._run_boolean_field_query(
            EventPropertyFilter(
                type="event",
                key="boolean_field",
                operator=PropertyOperator.IS_NOT_SET,
                value=PropertyOperator.IS_NOT_SET,
            )
        )

        self.assertEqual({"p_notset", "p_null"}, {row[0]["distinct_id"] for row in results})

    def test_is_set_boolean(self):
        self._create_boolean_field_test_events()

        results = self._run_boolean_field_query(
            EventPropertyFilter(
                type="event",
                key="boolean_field",
                operator=PropertyOperator.IS_SET,
                value=PropertyOperator.IS_SET,
            )
        )

        self.assertEqual({"p_true", "p_false"}, {row[0]["distinct_id"] for row in results})

    def test_person_id_expands_to_distinct_ids(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id1", "id2"],
        )
        flush_persons_and_events()
        person = Person.objects.first()
        query = EventsQuery(kind="EventsQuery", select=["*"], personId=str(person.pk))  # type: ignore

        # matching team
        query_ast = EventsQueryRunner(query=query, team=self.team).to_query()
        where_expr = cast(ast.CompareOperation, cast(ast.And, query_ast.where).exprs[0])
        right_expr = cast(ast.Tuple, where_expr.right)
        self.assertEqual(
            [cast(ast.Constant, cast(ast.Call, x).args[0]).value for x in right_expr.exprs], ["id1", "id2"]
        )

        # another team
        another_team = Team.objects.create(organization=Organization.objects.create())
        query_ast = EventsQueryRunner(query=query, team=another_team).to_query()
        where_expr = cast(ast.CompareOperation, cast(ast.And, query_ast.where).exprs[0])
        right_expr = cast(ast.Tuple, where_expr.right)
        self.assertEqual(right_expr.exprs, [])

    def test_test_account_filters(self):
        self.team.test_account_filters = [
            {
                "key": "email",
                "type": "person",
                "value": "posthog.com",
                "operator": "not_icontains",
            }
        ]
        self.team.save()
        query = EventsQuery(kind="EventsQuery", select=["*"], filterTestAccounts=True)
        query_ast = EventsQueryRunner(query=query, team=self.team).to_query()
        where_expr = cast(ast.CompareOperation, cast(ast.And, query_ast.where).exprs[0])
        right_expr = cast(ast.Constant, where_expr.right)
        self.assertEqual(right_expr.value, "%posthog.com%")
        self.assertEqual(where_expr.op, CompareOperationOp.NotILike)

    def test_big_int(self):
        BIG_INT = 2**159 - 24
        self._create_events(
            data=[
                (
                    "p_null",
                    "2020-01-11T12:00:04Z",
                    {"boolean_field": None, "bigInt": BIG_INT},
                ),
            ]
        )

        flush_persons_and_events()

        with freeze_time("2020-01-11T12:01:00"):
            query = EventsQuery(
                after="-24h",
                event="$pageview",
                kind="EventsQuery",
                orderBy=["timestamp ASC"],
                select=["*"],
            )

            runner = EventsQueryRunner(query=query, team=self.team)
            response = runner.run()
            assert isinstance(response, CachedEventsQueryResponse)
            assert response.results[0][0]["properties"]["bigInt"] == float(BIG_INT)

    def test_escaped_single_quotes_in_where_clause(self):
        SINGLE_QUOTE = "I'm a string with a ' in it"
        DOUBLE_QUOTE = 'I"m a string with a " in it'
        self._create_events(
            data=[
                (
                    "p_null",
                    "2020-01-11T12:00:04Z",
                    {"boolean_field": None, "arr_field": [SINGLE_QUOTE]},
                ),
                (
                    "p_one",
                    "2020-01-11T12:00:14Z",
                    {"boolean_field": None, "arr_field": [DOUBLE_QUOTE]},
                ),
            ]
        )

        flush_persons_and_events()

        with freeze_time("2020-01-11T12:01:00"):
            query = EventsQuery(
                after="-24h",
                event="$pageview",
                kind="EventsQuery",
                where=[
                    "has(JSONExtract(ifNull(properties.arr_field,'[]'),'Array(String)'), 'I\\'m a string with a \\' in it')"
                ],
                orderBy=["timestamp ASC"],
                select=["*"],
            )

            runner = EventsQueryRunner(query=query, team=self.team)
            response = runner.run()
            assert isinstance(response, CachedEventsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][0]["properties"]["arr_field"] == [SINGLE_QUOTE]

            query = EventsQuery(
                after="-24h",
                event="$pageview",
                kind="EventsQuery",
                where=[
                    "has(JSONExtract(ifNull(properties.arr_field,'[]'),'Array(String)'), 'I\"m a string with a \" in it')"
                ],
                orderBy=["timestamp ASC"],
                select=["*"],
            )

            runner = EventsQueryRunner(query=query, team=self.team)
            response = runner.run()
            assert isinstance(response, CachedEventsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][0]["properties"]["arr_field"] == [DOUBLE_QUOTE]

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_absolute_date_range(self):
        self._create_events(
            data=[
                (  # Event two hours BEFORE THE START of the day
                    "p17",
                    "2020-01-11T22:00:00",
                    {},
                ),
                (  # Event one hour after the start of the day
                    "p2",
                    "2020-01-12T01:00:00",
                    {},
                ),
                (  # Event right in the middle of the day
                    "p3",
                    "2020-01-12T12:00:00",
                    {},
                ),
                (  # Event one hour before the end of the day
                    "p1",
                    "2020-01-12T23:00:00",
                    {},
                ),
                (  # Event two hours AFTER THE END of the day
                    "p3",
                    "2020-01-13T02:00:00",
                    {},
                ),
            ]
        )

        flush_persons_and_events()

        query = EventsQuery(
            after="2020-01-12",
            before="2020-01-12T23:59:59",
            event="$pageview",
            kind="EventsQuery",
            orderBy=["timestamp ASC"],
            select=["*"],
        )

        runner = EventsQueryRunner(query=query, team=self.team)

        response = runner.run()
        assert isinstance(response, CachedEventsQueryResponse)
        assert [row[0]["timestamp"] for row in response.results] == [
            datetime(2020, 1, 12, 1, 0, 0, tzinfo=self.team.timezone_info),
            datetime(2020, 1, 12, 12, 0, 0, tzinfo=self.team.timezone_info),
            datetime(2020, 1, 12, 23, 0, 0, tzinfo=self.team.timezone_info),
        ]

    def test_event_metadata_filter(self):
        self._create_events(
            data=[
                (
                    "p17",
                    "2020-01-11T22:00:00",
                    {},
                ),
                (
                    "p2",
                    "2020-01-12T01:00:00",
                    {},
                ),
                (
                    "p3",
                    "2020-01-12T12:00:00",
                    {},
                ),
                (
                    "p1",
                    "2020-01-12T23:00:00",
                    {},
                ),
                (
                    "p3",
                    "2020-01-13T02:00:00",
                    {},
                ),
            ]
        )

        flush_persons_and_events()

        with freeze_time("2020-01-11T12:01:00"):
            query = EventsQuery(
                after="2020-01-11",
                before="2020-01-15",
                event="$pageview",
                kind="EventsQuery",
                orderBy=["timestamp ASC"],
                select=["*"],
                properties=[
                    EventMetadataPropertyFilter(
                        type="event_metadata", operator="exact", key="distinct_id", value=["p3"]
                    )
                ],
            )

            runner = EventsQueryRunner(query=query, team=self.team)

            response = runner.run()
            assert isinstance(response, CachedEventsQueryResponse)
            assert [row[0]["timestamp"] for row in response.results] == [
                datetime(2020, 1, 12, 12, 0, 0, tzinfo=self.team.timezone_info),
                datetime(2020, 1, 13, 2, 0, 0, tzinfo=self.team.timezone_info),
            ]

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21")
    def test_element_chain_property_filter(self):
        # Create an event with 'div' in elements_chain
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="test_user",
            properties={"attr": "has div"},
            elements=[
                Element(
                    tag_name="a",
                    href="/test-url",
                    attr_class=["link"],
                    text="Click me",
                    attributes={},
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(
                    tag_name="div",
                    attr_class=["container"],
                    attr_id="main-container",
                    nth_child=0,
                    nth_of_type=0,
                ),
                Element(
                    tag_name="button",
                    attr_class=["btn", "btn-primary"],
                    text="Submit",
                    nth_child=0,
                    nth_of_type=0,
                ),
            ],
        )

        # Create an event without elements_chain
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="test_user",
            properties={"attr": "no div"},
            elements=[
                Element(
                    tag_name="a",
                    href="/test-url",
                    attr_class=["link"],
                    text="Click me",
                    attributes={},
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(
                    tag_name="button",
                    attr_class=["btn", "btn-primary"],
                    text="Submit",
                    nth_child=0,
                    nth_of_type=0,
                ),
            ],
        )

        # Filter for events with a specific element text in the elements chain with $elements_chain not_icontains
        query = EventsQuery(
            after="-24h",
            event="$autocapture",
            kind="EventsQuery",
            orderBy=["timestamp ASC"],
            select=["*"],
            properties=[
                EventPropertyFilter(
                    key="$elements_chain",
                    value="div",
                    operator=PropertyOperator.NOT_ICONTAINS,
                    type="event",
                )
            ],
        )

        runner = EventsQueryRunner(query=query, team=self.team)
        response = runner.run()
        assert isinstance(response, CachedEventsQueryResponse)
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0][0]["properties"]["attr"], "no div")

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21")
    def test_presorted_events_table(self):
        self._create_events(
            data=[
                (
                    "p1",
                    "2020-01-20T12:00:04Z",
                    {"some_prop": "a"},
                ),
                (
                    "p2",
                    "2020-01-20T12:00:14Z",
                    {"some_prop": "b"},
                ),
            ]
        )
        self._create_events(
            data=[
                (
                    "p3",
                    "2020-01-20T12:00:04Z",
                    {"some_prop": "a"},
                ),
            ],
            event="$pageleave",
        )
        flush_persons_and_events()
        query = EventsQuery(
            after="-7d",
            event="$pageview",
            kind="EventsQuery",
            orderBy=["timestamp ASC"],
            select=["*"],
            properties=[
                EventPropertyFilter(
                    key="some_prop",
                    value="a",
                    operator=PropertyOperator.EXACT,
                    type="event",
                )
            ],
        )

        runner_regular = EventsQueryRunner(query=query, team=self.team)
        response_regular = runner_regular.run()

        runner_presorted = EventsQueryRunner(
            query=query, team=self.team, modifiers=HogQLQueryModifiers(usePresortedEventsTable=True)
        )
        response_presorted = runner_presorted.run()

        assert isinstance(response_regular, CachedEventsQueryResponse)
        assert isinstance(response_presorted, CachedEventsQueryResponse)

        assert "cityHash" not in response_regular.hogql
        assert "cityHash" in response_presorted.hogql

        assert response_regular.results == response_presorted.results

    def test_select_person_column(self):
        self._create_events(
            [
                ("id3", "2020-01-11T12:00:01Z", {"some": "thing"}),
                ("id4", "2020-01-11T12:00:02Z", {"some": "other"}),
            ]
        )
        flush_persons_and_events()

        query = EventsQuery(
            kind="EventsQuery",
            select=["person"],
            orderBy=["timestamp ASC"],
        )
        runner = EventsQueryRunner(query=query, team=self.team)
        response = runner.run()
        assert isinstance(response, CachedEventsQueryResponse)
        # Should return two rows, each with a person dict
        for row in response.results:
            person = row[0]
            assert isinstance(person, dict)
            assert person["properties"]["foo"] == "bar"
            assert person["distinct_id"] in ["id1", "id2"]
            assert "uuid" in person
            assert "created_at" in person

    def test_person_display_name_field(self):
        # Default: no custom display name properties
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email", "id_anon"],
            properties={"email": "user@email.com", "name": "Test User"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_email",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_anon",
            properties={},
        )
        flush_persons_and_events()

        query = EventsQuery(
            kind="EventsQuery",
            select=["event", "person_display_name -- Person"],
            orderBy=["timestamp ASC"],
        )
        runner = EventsQueryRunner(query=query, team=self.team)
        response = runner.run()
        assert isinstance(response, CachedEventsQueryResponse)
        # Should use default display name property (email)
        display_names = [row[1]["display_name"] for row in response.results]
        assert set(display_names) == {"user@email.com"}

    def test_person_display_name_field_2(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email", "id_anon"],
            properties={"email": "user@email.com", "name": "Test User"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_email",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_anon",
            properties={},
        )
        flush_persons_and_events()

        # Now set custom person_display_name_properties on team
        self.team.person_display_name_properties = ["name"]
        self.team.save()
        self.team.refresh_from_db()
        query = EventsQuery(
            kind="EventsQuery",
            select=["event", "person_display_name -- Person"],
            orderBy=["timestamp ASC"],
        )
        runner = EventsQueryRunner(query=query, team=self.team)
        response = runner.run()
        assert isinstance(response, CachedEventsQueryResponse)
        display_names = [row[1]["display_name"] for row in response.results]
        assert set(display_names) == {"Test User"}

    def test_person_display_name_field_fallback(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email", "id_anon"],
            properties={"email": "user@email.com", "name": "Test User"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_email",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_anon",
            properties={},
        )
        flush_persons_and_events()

        # If property is missing, fallback to distinct_id
        self.team.person_display_name_properties = ["nonexistent"]
        self.team.save()
        self.team.refresh_from_db()
        query = EventsQuery(
            kind="EventsQuery",
            select=["event", "person_display_name -- Person"],
            orderBy=["timestamp ASC"],
        )
        runner = EventsQueryRunner(query=query, team=self.team)
        response = runner.run()
        assert isinstance(response, CachedEventsQueryResponse)
        display_names = [row[1]["display_name"] for row in response.results]
        assert set(display_names) == {"id_email", "id_anon"}

    def test_person_display_name_field_with_spaces_in_property_name(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_spaced"],
            properties={"email": "user@email.com", "Property With Spaces": "Test User With Spaces"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_spaced",
            properties={},
        )
        flush_persons_and_events()

        # Configure the team to use the property with spaces as display name
        self.team.person_display_name_properties = ["Property With Spaces"]
        self.team.save()
        self.team.refresh_from_db()

        query = EventsQuery(
            kind="EventsQuery",
            select=["event", "person_display_name -- Person"],
            orderBy=["timestamp ASC"],
        )
        runner = EventsQueryRunner(query=query, team=self.team)
        response = runner.run()
        assert isinstance(response, CachedEventsQueryResponse)
        display_names = [row[1]["display_name"] for row in response.results]
        assert set(display_names) == {"Test User With Spaces"}

    def test_virtual_property(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_spaced"],
            properties={
                "email": "user@email.com",
                "Property With Spaces": "Test User With Spaces",
                "$initial_utm_source": "facebook",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_spaced",
            properties={"utm_source": "facebook"},
        )
        flush_persons_and_events()

        # Configure the team to use the property with spaces as display name
        self.team.person_display_name_properties = ["Property With Spaces"]
        self.team.save()
        self.team.refresh_from_db()

        query = EventsQuery(
            kind="EventsQuery",
            select=["event", "person_display_name -- Person", "person.properties.$virt_initial_channel_type"],
            orderBy=["timestamp ASC"],
        )
        runner = EventsQueryRunner(query=query, team=self.team)
        response = runner.run()
        assert isinstance(response, CachedEventsQueryResponse)
        assert response.results[0][2] == "Organic Social"

    def test_orderby_person_display_name_field(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email", "id_anon"],
            properties={"email": "user@email.com", "name": "Test User"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["id_email_2", "id_anon_2"],
            properties={"email": "user2@email.com", "name": "Test User 2"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_email",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_email_2",
            properties={},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_email_2",
            properties={},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="id_anon",
            properties={},
        )
        flush_persons_and_events()

        query = EventsQuery(
            kind="EventsQuery",
            select=["event", "person_display_name -- Person"],
            orderBy=["person_display_name -- Person  DESC"],
        )
        runner = EventsQueryRunner(query=query, team=self.team)
        response = runner.run()
        assert isinstance(response, CachedEventsQueryResponse)
        # Should use default display name property (email)
        display_names = [row[1]["display_name"] for row in response.results]
        assert display_names[0] == "user@email.com"
