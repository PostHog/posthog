import json
from unittest import mock
from unittest.mock import patch

from freezegun import freeze_time
from rest_framework import status

from posthog.api.services.query import process_query
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.models.utils import UUIDT
from posthog.schema import (
    EventPropertyFilter,
    EventsQuery,
    HogQLPropertyFilter,
    HogQLQuery,
    HogQLQueryResponse,
    PersonPropertyFilter,
    PropertyOperator,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    ENDPOINT = "query"

    @snapshot_clickhouse_queries
    def test_select_hogql_expressions(self):
        with freeze_time("2020-01-10 12:00:00"):
            _create_person(
                properties={"email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val3"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(
                select=[
                    "properties.key",
                    "event",
                    "distinct_id",
                    "concat(event, ' ', properties.key)",
                ]
            )
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(
                response,
                response
                | {
                    "columns": [
                        "properties.key",
                        "event",
                        "distinct_id",
                        "concat(event, ' ', properties.key)",
                    ],
                    "hasMore": False,
                    "results": [
                        ["test_val1", "sign up", "2", "sign up test_val1"],
                        ["test_val2", "sign out", "2", "sign out test_val2"],
                        ["test_val2", "sign out", "2", "sign out test_val2"],
                        ["test_val3", "sign out", "2", "sign out test_val3"],
                    ],
                    "types": ["Nullable(String)", "String", "String", "String"],
                },
            )

            query.select = ["*", "event"]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(response["columns"], ["*", "event"])
            self.assertIn("Tuple(", response["types"][0])
            self.assertEqual(response["types"][1], "String")
            self.assertEqual(len(response["results"]), 4)
            self.assertIsInstance(response["results"][0][0], dict)
            self.assertIsInstance(response["results"][0][1], str)

            query.select = ["count()", "event"]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(
                response,
                response
                | {
                    "columns": ["count()", "event"],
                    "hasMore": False,
                    "types": ["UInt64", "String"],
                    "results": [[3, "sign out"], [1, "sign up"]],
                },
            )

            query.select = ["count()", "event"]
            query.where = ["event == 'sign up' or like(properties.key, '%val2')"]
            query.orderBy = ["count() DESC", "event"]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(
                response,
                response
                | {
                    "columns": ["count()", "event"],
                    "hasMore": False,
                    "types": ["UInt64", "String"],
                    "results": [[2, "sign out"], [1, "sign up"]],
                },
            )

    @also_test_with_materialized_columns(["key"])
    @snapshot_clickhouse_queries
    def test_hogql_property_filter(self):
        with freeze_time("2020-01-10 12:00:00"):
            _create_person(
                properties={"email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="3",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="4",
                properties={"key": "test_val3"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(
                select=[
                    "event",
                    "distinct_id",
                    "properties.key",
                    "'a%sd'",
                    "concat(event, ' ', properties.key)",
                ]
            )

            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 4)

            query.properties = [HogQLPropertyFilter(type="hogql", key="'a%sd' == 'foo'")]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 0)

            query.properties = [HogQLPropertyFilter(type="hogql", key="'a%sd' == 'a%sd'")]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 4)

            query.properties = [HogQLPropertyFilter(type="hogql", key="properties.key == 'test_val2'")]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 2)

    @also_test_with_materialized_columns(event_properties=["key", "path"])
    @snapshot_clickhouse_queries
    def test_event_property_filter(self):
        with freeze_time("2020-01-10 12:00:00"):
            _create_person(
                properties={"email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="3",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="4",
                properties={"key": "test_val3", "path": "a/b/c"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(
                select=[
                    "event",
                    "distinct_id",
                    "properties.key",
                    "'a%sd'",
                    "concat(event, ' ', properties.key)",
                ]
            )
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 4)

            query.properties = [
                EventPropertyFilter(
                    type="event",
                    key="key",
                    value="test_val3",
                    operator=PropertyOperator.exact,
                )
            ]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 1)

            query.properties = [
                EventPropertyFilter(
                    type="event",
                    key="path",
                    value="/",
                    operator=PropertyOperator.icontains,
                )
            ]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 1)

    @also_test_with_materialized_columns(event_properties=["key"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_person_property_filter(self):
        with freeze_time("2020-01-10 12:00:00"):
            _create_person(
                properties={"email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="3",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="4",
                properties={"key": "test_val3"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(
                select=[
                    "event",
                    "distinct_id",
                    "properties.key",
                    "'a%sd'",
                    "concat(event, ' ', properties.key)",
                ],
                properties=[
                    PersonPropertyFilter(
                        type="person",
                        key="email",
                        value="tom@posthog.com",
                        operator=PropertyOperator.exact,
                    )
                ],
            )
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 2)

    def test_safe_clickhouse_error_passed_through(self):
        query = {"kind": "EventsQuery", "select": ["timestamp + 'string'"]}

        response_post = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query})
        self.assertEqual(response_post.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_post.json(),
            self.validation_error_response(
                "Illegal types DateTime64(6, 'UTC') and String of arguments of function plus: "
                "While processing toTimeZone(timestamp, 'UTC') + 'string'.",
                "illegal_type_of_argument",
            ),
        )

    @patch("sqlparse.format", return_value="SELECT 1&&&")  # Erroneously constructed SQL
    def test_unsafe_clickhouse_error_is_swallowed(self, sqlparse_format_mock):
        query = {"kind": "EventsQuery", "select": ["timestamp"]}

        response_post = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query})
        self.assertEqual(response_post.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @also_test_with_materialized_columns(event_properties=["key", "path"])
    @snapshot_clickhouse_queries
    def test_property_filter_aggregations(self):
        with freeze_time("2020-01-10 12:00:00"):
            _create_person(
                properties={"email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="3",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="4",
                properties={"key": "test_val3", "path": "a/b/c"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(select=["properties.key", "count()"])
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 3)

            query.where = ["count() > 1"]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 1)

    @snapshot_clickhouse_queries
    def test_select_event_person(self):
        with freeze_time("2020-01-10 12:00:00"):
            person = _create_person(
                properties={"name": "Tom", "email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="3",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="4",
                properties={"key": "test_val3", "path": "a/b/c"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(select=["event", "person", "person -- P"])
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 4)
            self.assertEqual(response["results"][0][1], {"distinct_id": "4"})
            self.assertEqual(response["results"][1][1], {"distinct_id": "3"})
            self.assertEqual(response["results"][1][2], {"distinct_id": "3"})
            expected_user = {
                "uuid": str(person.uuid),
                "properties": {"name": "Tom", "email": "tom@posthog.com"},
                "distinct_id": "2",
                "created_at": "2020-01-10T12:00:00Z",
            }
            self.assertEqual(response["results"][2][1], expected_user)
            self.assertEqual(response["results"][3][1], expected_user)
            self.assertEqual(response["results"][3][2], expected_user)

    @snapshot_clickhouse_queries
    def test_events_query_all_time_date(self):
        with freeze_time("2020-01-10 12:00:00"):
            _create_person(
                properties={"name": "Tom", "email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                properties={"key": "test_val1"},
            )
        with freeze_time("2021-01-10 12:11:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2022-01-10 12:12:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="3",
                properties={"key": "test_val2"},
            )
        with freeze_time("2023-01-10 12:13:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="4",
                properties={"key": "test_val3", "path": "a/b/c"},
            )
        flush_persons_and_events()

        with freeze_time("2023-01-12 12:14:00"):
            query = EventsQuery(select=["event"], after="all")
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 4)

            query = EventsQuery(select=["event"], before="-1y", after="all")
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 3)

            query = EventsQuery(select=["event"], before="2022-01-01", after="-4y")
            response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 2)

    @also_test_with_materialized_columns(event_properties=["key"])
    @snapshot_clickhouse_queries
    def test_full_hogql_query(self):
        with freeze_time("2020-01-10 12:00:00"):
            _create_person(
                properties={"email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="3",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="4",
                properties={"key": "test_val3", "path": "a/b/c"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = HogQLQuery(query="select event, distinct_id, properties.key from events order by timestamp")
            api_response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            query.response = HogQLQueryResponse.model_validate(api_response)

            self.assertEqual(query.response.results and len(query.response.results), 4)
            self.assertEqual(
                query.response.results,
                [
                    ["sign up", "2", "test_val1"],
                    ["sign out", "2", "test_val2"],
                    ["sign out", "3", "test_val2"],
                    ["sign out", "4", "test_val3"],
                ],
            )

    @patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 10)
    @patch("posthog.hogql.constants.MAX_SELECT_RETURNED_ROWS", 15)
    def test_full_hogql_query_limit(self, MAX_SELECT_RETURNED_ROWS=15, DEFAULT_RETURNED_ROWS=10):
        random_uuid = str(UUIDT())
        with freeze_time("2020-01-10 12:00:00"):
            for _ in range(20):
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=random_uuid,
                    properties={"key": "test_val1"},
                )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            response = process_query(
                team=self.team,
                query_json={
                    "kind": "HogQLQuery",
                    "query": f"select event from events where distinct_id='{random_uuid}'",
                },
            )
            self.assertEqual(len(response.get("results", [])), 10)

    @patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 10)
    @patch("posthog.hogql.constants.MAX_SELECT_RETURNED_ROWS", 15)
    def test_full_hogql_query_limit_exported(self, MAX_SELECT_RETURNED_ROWS=15, DEFAULT_RETURNED_ROWS=10):
        random_uuid = str(UUIDT())
        with freeze_time("2020-01-10 12:00:00"):
            for _ in range(20):
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=random_uuid,
                    properties={"key": "test_val1"},
                )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            response = process_query(
                team=self.team,
                query_json={
                    "kind": "HogQLQuery",
                    "query": f"select event from events where distinct_id='{random_uuid}'",
                },
                in_export_context=True,  # This is the only difference
            )
            self.assertEqual(len(response.get("results", [])), 15)

    @patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 10)
    @patch("posthog.hogql.constants.MAX_SELECT_RETURNED_ROWS", 15)
    def test_full_events_query_limit(self, MAX_SELECT_RETURNED_ROWS=15, DEFAULT_RETURNED_ROWS=10):
        random_uuid = str(UUIDT())
        with freeze_time("2020-01-10 12:00:00"):
            for _ in range(20):
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=random_uuid,
                    properties={"key": "test_val1"},
                )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            response = process_query(
                team=self.team,
                query_json={
                    "kind": "EventsQuery",
                    "select": ["event"],
                    "where": [f"distinct_id = '{random_uuid}'"],
                },
            )

        self.assertEqual(len(response.get("results", [])), 10)

    @patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 10)
    @patch("posthog.hogql.constants.MAX_SELECT_RETURNED_ROWS", 15)
    def test_full_events_query_limit_exported(self, MAX_SELECT_RETURNED_ROWS=15, DEFAULT_RETURNED_ROWS=10):
        random_uuid = str(UUIDT())
        with freeze_time("2020-01-10 12:00:00"):
            for _ in range(20):
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=random_uuid,
                    properties={"key": "test_val1"},
                )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            response = process_query(
                team=self.team,
                query_json={
                    "kind": "EventsQuery",
                    "select": ["event"],
                    "where": [f"distinct_id = '{random_uuid}'"],
                },
                in_export_context=True,
            )

        self.assertEqual(len(response.get("results", [])), 15)

    def test_property_definition_annotation_does_not_break_things(self):
        PropertyDefinition.objects.create(team=self.team, name="$browser", property_type=PropertyType.String)

        with freeze_time("2020-01-10 12:14:00"):
            response = process_query(
                team=self.team,
                query_json={
                    "kind": "EventsQuery",
                    "select": ["event"],
                    # This used to cause query failure when tried to add an annotation for a node without location
                    # (which properties.$browser is in this case)
                    "properties": [
                        {
                            "type": "event",
                            "key": "$browser",
                            "operator": "is_not",
                            "value": "Foo",
                        }
                    ],
                },
            )
        self.assertEqual(response.get("columns"), ["event"])

    def test_invalid_query_kind(self):
        api_response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": {"kind": "Tomato Soup"}})
        assert api_response.status_code == 400
        assert api_response.json()["code"] == "parse_error"
        assert "validation errors for QuerySchema" in api_response.json()["detail"]
        assert "type=literal_error, input_value='Tomato Soup'" in api_response.json()["detail"]

    @snapshot_clickhouse_queries
    def test_full_hogql_query_view(self):
        with freeze_time("2020-01-10 12:00:00"):
            _create_person(
                properties={"email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="2",
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="2",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="3",
                properties={"key": "test_val2"},
            )
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team,
                event="sign out",
                distinct_id="4",
                properties={"key": "test_val3", "path": "a/b/c"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            self.client.post(
                f"/api/projects/{self.team.id}/warehouse_saved_queries/",
                {
                    "name": "event_view",
                    "query": {
                        "kind": "HogQLQuery",
                        "query": f"select event AS event, distinct_id as distinct_id, properties.key as key from events order by timestamp",
                    },
                },
            )
            query = HogQLQuery(query="select * from event_view")
            api_response = self.client.post(f"/api/projects/{self.team.id}/query/", {"query": query.dict()}).json()
            query.response = HogQLQueryResponse.model_validate(api_response)

            self.assertEqual(query.response.results and len(query.response.results), 4)
            self.assertEqual(
                query.response.results,
                [
                    ["sign up", "2", "test_val1"],
                    ["sign out", "2", "test_val2"],
                    ["sign out", "3", "test_val2"],
                    ["sign out", "4", "test_val3"],
                ],
            )

    def test_full_hogql_query_values(self):
        random_uuid = str(UUIDT())
        with freeze_time("2020-01-10 12:00:00"):
            for _ in range(20):
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id=random_uuid,
                    properties={"key": "test_val1"},
                )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            response = process_query(
                team=self.team,
                query_json={
                    "kind": "HogQLQuery",
                    "query": "select count() from events where distinct_id = {random_uuid}",
                    "values": {"random_uuid": random_uuid},
                },
            )

        self.assertEqual(response.get("results", [])[0][0], 20)


class TestQueryRetrieve(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team_id = self.team.pk
        self.valid_query_id = "12345"
        self.invalid_query_id = "invalid-query-id"
        self.redis_client_mock = mock.Mock()
        self.redis_get_patch = mock.patch("posthog.redis.get_client", return_value=self.redis_client_mock)
        self.redis_get_patch.start()

    def tearDown(self):
        self.redis_get_patch.stop()

    def test_with_valid_query_id(self):
        self.redis_client_mock.get.return_value = json.dumps(
            {
                "id": self.valid_query_id,
                "team_id": self.team_id,
                "error": False,
                "complete": True,
                "results": ["result1", "result2"],
            }
        ).encode()
        response = self.client.get(f"/api/projects/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["complete"], True, response.content)

    def test_with_invalid_query_id(self):
        self.redis_client_mock.get.return_value = None
        response = self.client.get(f"/api/projects/{self.team.id}/query/{self.invalid_query_id}/")
        self.assertEqual(response.status_code, 404)

    def test_completed_query(self):
        self.redis_client_mock.get.return_value = json.dumps(
            {
                "id": self.valid_query_id,
                "team_id": self.team_id,
                "complete": True,
                "results": ["result1", "result2"],
            }
        ).encode()
        response = self.client.get(f"/api/projects/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["complete"])

    def test_running_query(self):
        self.redis_client_mock.get.return_value = json.dumps(
            {
                "id": self.valid_query_id,
                "team_id": self.team_id,
                "complete": False,
            }
        ).encode()
        response = self.client.get(f"/api/projects/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["complete"])

    def test_failed_query(self):
        self.redis_client_mock.get.return_value = json.dumps(
            {
                "id": self.valid_query_id,
                "team_id": self.team_id,
                "error": True,
                "error_message": "Query failed",
            }
        ).encode()
        response = self.client.get(f"/api/projects/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["error"])

    def test_destroy(self):
        self.redis_client_mock.get.return_value = json.dumps(
            {
                "id": self.valid_query_id,
                "team_id": self.team_id,
                "error": True,
                "error_message": "Query failed",
            }
        ).encode()
        response = self.client.delete(f"/api/projects/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 204)
        self.redis_client_mock.delete.assert_called_once()
