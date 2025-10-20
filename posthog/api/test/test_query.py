import json

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest import mock
from unittest.mock import patch

from rest_framework import status

from posthog.schema import (
    CachedEventsQueryResponse,
    CachedHogQLQueryResponse,
    CachedRetentionQueryResponse,
    DataWarehouseNode,
    EventPropertyFilter,
    EventsQuery,
    FunnelsQuery,
    HogQLPropertyFilter,
    HogQLQuery,
    MeanRetentionCalculation,
    PersonPropertyFilter,
    PropertyOperator,
    RetentionQuery,
)

from posthog.hogql.constants import LimitContext

from posthog.api.services.query import process_query_dict
from posthog.models.insight_variable import InsightVariable
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.models.utils import UUIDT


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
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
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
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(response["columns"], ["*", "event"])
            self.assertIn("Tuple(", response["types"][0])
            self.assertEqual(response["types"][1], "String")
            self.assertEqual(len(response["results"]), 4)
            self.assertIsInstance(response["results"][0][0], dict)
            self.assertIsInstance(response["results"][0][1], str)

            query.select = ["count()", "event"]
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
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
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
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

            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 4)

            query.properties = [HogQLPropertyFilter(type="hogql", key="'a%sd' == 'foo'")]
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 0)

            query.properties = [HogQLPropertyFilter(type="hogql", key="'a%sd' == 'a%sd'")]
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 4)

            query.properties = [HogQLPropertyFilter(type="hogql", key="properties.key == 'test_val2'")]
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
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
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 4)

            query.properties = [
                EventPropertyFilter(
                    type="event",
                    key="key",
                    value="test_val3",
                    operator=PropertyOperator.EXACT,
                )
            ]
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 1)

            query.properties = [
                EventPropertyFilter(
                    type="event",
                    key="path",
                    value="/",
                    operator=PropertyOperator.ICONTAINS,
                )
            ]
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
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
                        operator=PropertyOperator.EXACT,
                    )
                ],
            )
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 2)

    def test_safe_clickhouse_error_passed_through(self):
        query = {"kind": "EventsQuery", "select": ["timestamp + 'string'"]}

        with freeze_time("2024-10-16 22:10:29.691212"):
            response_post = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query})
            self.assertEqual(response_post.status_code, status.HTTP_400_BAD_REQUEST)

            self.assertEqual(
                response_post.json(),
                {
                    "type": "validation_error",
                    "code": "illegal_type_of_argument",
                    "detail": f"Illegal types DateTime64(6, 'UTC') and String of arguments of function plus: In scope SELECT toTimeZone(events.timestamp, 'UTC') + 'string' FROM events WHERE (events.team_id = {self.team.id}) AND (toTimeZone(events.timestamp, 'UTC') < toDateTime64('2024-10-16 22:10:34.691212', 6, 'UTC')) AND (toTimeZone(events.timestamp, 'UTC') > toDateTime64('2024-10-15 22:10:29.691212', 6, 'UTC')) ORDER BY toTimeZone(events.timestamp, 'UTC') + 'string' ASC LIMIT 0, 101 SETTINGS readonly = 2, max_execution_time = 60, allow_experimental_object_type = 1, format_csv_allow_double_quotes = 0, max_ast_elements = 4000000, max_expanded_ast_elements = 4000000, max_bytes_before_external_group_by = 0, transform_null_in = 1, optimize_min_equality_disjunction_chain_length = 4294967295, allow_experimental_join_condition = 1.",
                    "attr": None,
                },
            )

    @patch(
        "posthog.clickhouse.client.execute._annotate_tagged_query", return_value=("SELECT 1&&&", {})
    )  # Erroneously constructed SQL
    def test_unsafe_clickhouse_error_is_swallowed(self, sqlparse_format_mock):
        query = {"kind": "EventsQuery", "select": ["timestamp"]}

        response_post = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query})
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
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 3)

            query.where = ["count() > 1"]
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
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
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
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
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 4)

            query = EventsQuery(select=["event"], before="-1y", after="all")
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            self.assertEqual(len(response["results"]), 3)

            query = EventsQuery(select=["event"], before="2022-01-01", after="-4y")
            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
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
            api_response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()}).json()
            response = CachedHogQLQueryResponse.model_validate(api_response)

            self.assertEqual(response.results and len(response.results), 4)
            self.assertEqual(
                response.results,
                [
                    ["sign up", "2", "test_val1"],
                    ["sign out", "2", "test_val2"],
                    ["sign out", "3", "test_val2"],
                    ["sign out", "4", "test_val3"],
                ],
            )

    def test_query_with_source(self):
        query = {
            "kind": "DataTableNode",
            "source": {
                "kind": "HogQLQuery",
                "query": "SELECT event from events",
            },
        }
        response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_query_not_supported(self):
        query = {
            "kind": "SavedInsightNode",
            "shortId": "123",
        }
        response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Unsupported query kind: SavedInsightNode", response.content)

    @patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 10)
    @patch("posthog.hogql.constants.MAX_SELECT_RETURNED_ROWS", 15)
    def test_full_hogql_query_limit(self, MAX_SELECT_RETURNED_ROWS=15, DEFAULT_RETURNED_ROWS=10):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
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
            response = process_query_dict(
                team=self.team,
                query_json={
                    "kind": "HogQLQuery",
                    "query": f"select event from events where distinct_id='{random_uuid}'",
                },
            )
        assert isinstance(response, CachedHogQLQueryResponse)
        self.assertEqual(len(response.results), 10)

    @patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 10)
    @patch("posthog.hogql.constants.CSV_EXPORT_LIMIT", 15)
    def test_full_hogql_query_limit_exported(self, CSV_EXPORT_LIMIT=15, DEFAULT_RETURNED_ROWS=10):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
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
            response = process_query_dict(
                team=self.team,
                query_json={
                    "kind": "HogQLQuery",
                    "query": f"select event from events where distinct_id='{random_uuid}'",
                },
                limit_context=LimitContext.EXPORT,  # This is the only difference
            )
        assert isinstance(response, CachedHogQLQueryResponse)
        self.assertEqual(len(response.results), 15)

    @patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 10)
    @patch("posthog.hogql.constants.MAX_SELECT_RETURNED_ROWS", 15)
    def test_full_events_query_limit(self, MAX_SELECT_RETURNED_ROWS=15, DEFAULT_RETURNED_ROWS=10):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
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
            response = process_query_dict(
                team=self.team,
                query_json={
                    "kind": "EventsQuery",
                    "select": ["event"],
                    "where": [f"distinct_id = '{random_uuid}'"],
                },
            )

        assert isinstance(response, CachedEventsQueryResponse)
        self.assertEqual(len(response.results), 10)

    @patch("posthog.hogql.constants.DEFAULT_RETURNED_ROWS", 10)
    @patch("posthog.hogql.constants.CSV_EXPORT_LIMIT", 15)
    def test_full_events_query_limit_exported(self, CSV_EXPORT_LIMIT=15, DEFAULT_RETURNED_ROWS=10):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
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
            response = process_query_dict(
                team=self.team,
                query_json={
                    "kind": "EventsQuery",
                    "select": ["event"],
                    "where": [f"distinct_id = '{random_uuid}'"],
                },
                limit_context=LimitContext.EXPORT,
            )

        assert isinstance(response, CachedEventsQueryResponse)
        self.assertEqual(len(response.results), 15)

    def test_property_definition_annotation_does_not_break_things(self):
        PropertyDefinition.objects.create(team=self.team, name="$browser", property_type=PropertyType.String)

        with freeze_time("2020-01-10 12:14:00"):
            response = process_query_dict(
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
        assert isinstance(response, CachedEventsQueryResponse)
        self.assertEqual(response.columns, ["event"])

    def test_invalid_query_kind(self):
        api_response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": {"kind": "Tomato Soup"}})
        self.assertEqual(api_response.status_code, 400)
        self.assertEqual(api_response.json()["code"], "parse_error")
        self.assertIn("1 validation error for QueryRequest", api_response.json()["detail"], api_response.content)
        self.assertIn(
            "Input tag 'Tomato Soup' found using 'kind' does not match any of the expected tags",
            api_response.json()["detail"],
            api_response.content,
        )

    def test_funnel_query_with_data_warehouse_node_temporarily_raises(self):
        # As of September 2024, funnels don't support data warehouse tables YET, so we want a helpful error message
        api_response = self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {
                "query": FunnelsQuery(
                    series=[
                        DataWarehouseNode(
                            id="xyz",
                            table_name="xyz",
                            id_field="id",
                            distinct_id_field="customer_email",
                            timestamp_field="created",
                        ),
                        DataWarehouseNode(
                            id="abc",
                            table_name="abc",
                            id_field="id",
                            distinct_id_field="customer_email",
                            timestamp_field="timestamp",
                        ),
                    ],
                ).model_dump()
            },
        )
        self.assertEqual(api_response.status_code, 400)
        self.assertDictEqual(
            api_response.json(),
            self.validation_error_response(
                "Data warehouse tables are not supported in funnels just yet. For now, please try this funnel without the data warehouse-based step."
            ),
        )

    def test_missing_query(self):
        api_response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": {}})
        self.assertEqual(api_response.status_code, 400)

    def test_missing_body(self):
        api_response = self.client.post(f"/api/environments/{self.team.id}/query/")
        self.assertEqual(api_response.status_code, 400)

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
                f"/api/environments/{self.team.id}/warehouse_saved_queries/",
                {
                    "name": "event_view",
                    "query": {
                        "kind": "HogQLQuery",
                        "query": f"select event AS event, distinct_id as distinct_id, properties.key as key from events order by timestamp",
                    },
                },
            )
            query = HogQLQuery(query="select event, distinct_id, key from event_view")
            api_response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query.dict()})
            response = CachedHogQLQueryResponse.model_validate(api_response.json())

            self.assertEqual(api_response.status_code, 200)
            self.assertEqual(len(response.results), 4)
            self.assertEqual(
                response.results,
                [
                    ["sign up", "2", "test_val1"],
                    ["sign out", "2", "test_val2"],
                    ["sign out", "3", "test_val2"],
                    ["sign out", "4", "test_val3"],
                ],
            )

    @snapshot_clickhouse_queries
    def test_full_hogql_query_async(self):
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
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = HogQLQuery(query="select * from events")
            api_response = self.client.post(
                f"/api/environments/{self.team.id}/query/", {"query": query.dict(), "refresh": "force_async"}
            )

            self.assertEqual(api_response.status_code, 202)  # This means "Accepted" (for processing)
            self.assertEqual(
                api_response.json(),
                {
                    "query_status": {
                        "complete": False,
                        "pickup_time": None,
                        "end_time": None,
                        "error": False,
                        "error_message": None,
                        "expiration_time": mock.ANY,
                        "id": mock.ANY,
                        "query_async": True,
                        "results": None,
                        "start_time": "2020-01-10T12:14:00Z",
                        "task_id": mock.ANY,
                        "team_id": mock.ANY,
                        "insight_id": mock.ANY,
                        "dashboard_id": mock.ANY,
                        "query_progress": None,
                        "labels": None,
                    }
                },
            )

    def test_full_hogql_query_values(self):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
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
            response = process_query_dict(
                team=self.team,
                query_json={
                    "kind": "HogQLQuery",
                    "query": "select count() from events where distinct_id = {random_uuid}",
                    "values": {"random_uuid": random_uuid},
                },
            )

        assert isinstance(response, CachedHogQLQueryResponse)
        self.assertEqual(response.results[0][0], 20)

    def test_dashboard_filters_applied(self):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        with freeze_time("2020-01-07 12:00:00"):
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id=random_uuid,
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 15:00:00"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=random_uuid,
                properties={"key": "test_val1"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 19:00:00"):
            response_without_dashboard_filters = process_query_dict(
                team=self.team,
                query_json={
                    "kind": "HogQLQuery",
                    "query": "select count() from events where {filters}",
                },
            )
            response_with_dashboard_filters = process_query_dict(
                team=self.team,
                query_json={
                    "kind": "HogQLQuery",
                    "query": "select count() from events where {filters}",
                },
                dashboard_filters_json={"date_from": "2020-01-09", "date_to": "2020-01-11"},
            )

        assert isinstance(response_without_dashboard_filters, CachedHogQLQueryResponse)
        self.assertEqual(response_without_dashboard_filters.results, [(2,)])
        assert isinstance(response_with_dashboard_filters, CachedHogQLQueryResponse)
        self.assertEqual(response_with_dashboard_filters.results, [(1,)])

    def test_dashboard_filters_applied_with_source(self):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        with freeze_time("2020-01-07 12:00:00"):
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id=random_uuid,
                properties={"key": "test_val1"},
            )
        with freeze_time("2020-01-10 15:00:00"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=random_uuid,
                properties={"key": "test_val1"},
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 19:00:00"):
            response_without_dashboard_filters = process_query_dict(
                team=self.team,
                query_json={
                    "kind": "DataVisualizationNode",
                    "source": {
                        "kind": "HogQLQuery",
                        "query": "select count() from events where {filters}",
                    },
                },
            )
            response_with_dashboard_filters = process_query_dict(
                team=self.team,
                query_json={
                    "kind": "DataVisualizationNode",
                    "source": {
                        "kind": "HogQLQuery",
                        "query": "select count() from events where {filters}",
                    },
                },
                dashboard_filters_json={"date_from": "2020-01-09", "date_to": "2020-01-11"},
            )

        assert isinstance(response_without_dashboard_filters, CachedHogQLQueryResponse)
        self.assertEqual(response_without_dashboard_filters.results, [(2,)])
        assert isinstance(response_with_dashboard_filters, CachedHogQLQueryResponse)
        self.assertEqual(response_with_dashboard_filters.results, [(1,)])

    def test_dashboard_variables_overrides(self):
        variable = InsightVariable.objects.create(
            team=self.team, name="Test", code_name="test", default_value="some_default_value", type="String"
        )
        variable_id = str(variable.pk)
        variable_override_value = "helloooooo"

        api_response = self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select {variables.test}",
                    "explain": True,
                    "filters": {"dateRange": {"date_from": "-7d"}},
                    "variables": {
                        variable_id: {
                            "variableId": variable_id,
                            "code_name": variable.code_name,
                            "value": variable_override_value,
                        }
                    },
                },
                "client_query_id": "5d92fb51-5088-45e8-91b2-843aef3d69bd",
                "filters_override": None,
                "variables_override": {
                    variable_id: {
                        "code_name": variable.code_name,
                        "variableId": variable_id,
                        "value": variable_override_value,
                    }
                },
            },
        ).json()

        response = CachedHogQLQueryResponse.model_validate(api_response)
        assert response.results[0][0] == variable_override_value

    @patch("posthog.api.query.process_query_model")
    def test_upgrades_query(self, mock_process_query):
        mock_process_query.return_value = CachedRetentionQueryResponse(
            cache_key="cache_123",
            is_cached=False,
            last_refresh="2023-10-16T12:00:00Z",
            next_allowed_client_refresh="2023-10-16T14:00:00Z",
            results=[],
            timezone="UTC",
        )

        self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {
                "query": {
                    "kind": "RetentionQuery",
                    "retentionFilter": {
                        "period": "Day",
                        "totalIntervals": 8,
                        "targetEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                        "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                        "retentionType": "retention_first_time",
                        "showMean": True,
                    },
                },
                "client_query_id": "5d92fb51-5088-45e8-91b2-843aef3d69bd",
            },
        ).json()

        mock_process_query.assert_called_once()
        updated_query = mock_process_query.call_args.args[1]
        assert isinstance(updated_query, RetentionQuery)
        assert updated_query.version == 2
        assert updated_query.retentionFilter.meanRetentionCalculation == MeanRetentionCalculation.SIMPLE


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
        response = self.client.get(f"/api/environments/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["query_status"]["complete"], True, response.content)

    def test_with_invalid_query_id(self):
        self.redis_client_mock.get.return_value = None
        response = self.client.get(f"/api/environments/{self.team.id}/query/{self.invalid_query_id}/")
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
        response = self.client.get(f"/api/environments/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["query_status"]["complete"])

    def test_running_query(self):
        self.redis_client_mock.get.return_value = json.dumps(
            {
                "id": self.valid_query_id,
                "team_id": self.team_id,
                "complete": False,
            }
        ).encode()
        response = self.client.get(f"/api/environments/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["query_status"]["complete"])

    def test_failed_query_with_internal_error(self):
        self.redis_client_mock.get.return_value = json.dumps(
            {
                "id": self.valid_query_id,
                "team_id": self.team_id,
                "error": True,
                "error_message": None,
            }
        ).encode()
        response = self.client.get(f"/api/environments/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.json()["query_status"]["error"])

    def test_failed_query_with_exposed_error(self):
        self.redis_client_mock.get.return_value = json.dumps(
            {
                "id": self.valid_query_id,
                "team_id": self.team_id,
                "error": True,
                "error_message": "Try changing the time range",
            }
        ).encode()
        response = self.client.get(f"/api/environments/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["query_status"]["error"])

    def test_destroy(self):
        self.redis_client_mock.get.return_value = json.dumps(
            {
                "id": self.valid_query_id,
                "team_id": self.team_id,
                "error": True,
                "error_message": "Query failed",
            }
        ).encode()
        response = self.client.delete(f"/api/environments/{self.team.id}/query/{self.valid_query_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.redis_client_mock.delete.call_count, 2)


class TestQueryDraftSql(APIBaseTest):
    @patch("posthog.hogql.ai.hit_openai", return_value=("SELECT 1", 21, 37))
    def test_draft_sql(self, hit_openai_mock):
        response = self.client.get(
            f"/api/environments/{self.team.id}/query/draft_sql/", {"prompt": "I need the number 1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"sql": "SELECT 1"})
        hit_openai_mock.assert_called_once()


class TestQueryUpgrade(APIBaseTest):
    def test_upgrades_valid_query(self):
        query = {"kind": "RetentionQuery", "retentionFilter": {"period": "Day", "totalIntervals": 7, "showMean": True}}

        response = self.client.post(f"/api/environments/{self.team.id}/query/upgrade/", {"query": query})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "query": {
                    "kind": "RetentionQuery",
                    "retentionFilter": {"meanRetentionCalculation": "simple", "period": "Day", "totalIntervals": 7},
                    "version": 2,
                }
            },
        )
