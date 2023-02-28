from freezegun import freeze_time
from rest_framework import status

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
            _create_event(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val1"})
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(team=self.team, event="sign out", distinct_id="2", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(team=self.team, event="sign out", distinct_id="2", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(team=self.team, event="sign out", distinct_id="2", properties={"key": "test_val3"})
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(select=["properties.key", "event", "distinct_id", "concat(event, ' ', properties.key)"])
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(
                response,
                {
                    "columns": ["properties.key", "event", "distinct_id", "concat(event, ' ', properties.key)"],
                    "hasMore": False,
                    "results": [
                        ["test_val1", "sign up", "2", "sign up test_val1"],
                        ["test_val2", "sign out", "2", "sign out test_val2"],
                        ["test_val2", "sign out", "2", "sign out test_val2"],
                        ["test_val3", "sign out", "2", "sign out test_val3"],
                    ],
                    "types": ["String", "String", "String", "String"],
                },
            )

            query.select = ["*", "event"]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(response["columns"], ["*", "event"])
            self.assertIn("Tuple(", response["types"][0])
            self.assertEqual(response["types"][1], "String")
            self.assertEqual(len(response["results"]), 4)
            self.assertIsInstance(response["results"][0][0], dict)
            self.assertIsInstance(response["results"][0][1], str)

            query.select = ["count()", "event"]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(
                response,
                {
                    "columns": ["count()", "event"],
                    "hasMore": False,
                    "types": ["UInt64", "String"],
                    "results": [[3, "sign out"], [1, "sign up"]],
                },
            )

            query.select = ["count()", "event"]
            query.where = ["event == 'sign up' or like(properties.key, '%val2')"]
            query.orderBy = ["count() DESC", "event"]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(
                response,
                {
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
            _create_event(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val1"})
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(team=self.team, event="sign out", distinct_id="2", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(team=self.team, event="sign out", distinct_id="3", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(team=self.team, event="sign out", distinct_id="4", properties={"key": "test_val3"})
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(
                select=["event", "distinct_id", "properties.key", "'a%sd'", "concat(event, ' ', properties.key)"]
            )

            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(len(response["results"]), 4)

            query.properties = [HogQLPropertyFilter(type="hogql", key="'a%sd' == 'foo'")]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(len(response["results"]), 0)

            query.properties = [HogQLPropertyFilter(type="hogql", key="'a%sd' == 'a%sd'")]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(len(response["results"]), 4)

            query.properties = [HogQLPropertyFilter(type="hogql", key="properties.key == 'test_val2'")]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
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
            _create_event(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val1"})
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(team=self.team, event="sign out", distinct_id="2", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(team=self.team, event="sign out", distinct_id="3", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team, event="sign out", distinct_id="4", properties={"key": "test_val3", "path": "a/b/c"}
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(
                select=["event", "distinct_id", "properties.key", "'a%sd'", "concat(event, ' ', properties.key)"]
            )
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(len(response["results"]), 4)

            query.properties = [
                EventPropertyFilter(type="event", key="key", value="test_val3", operator=PropertyOperator.exact)
            ]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(len(response["results"]), 1)

            query.properties = [
                EventPropertyFilter(type="event", key="path", value="/", operator=PropertyOperator.icontains)
            ]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(len(response["results"]), 1)

    # TODO: events query person property filters don't use materialized columns!
    # @also_test_with_materialized_columns(event_properties=["key"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_person_property_filter(self):
        with freeze_time("2020-01-10 12:00:00"):
            _create_person(
                properties={"email": "tom@posthog.com"},
                distinct_ids=["2", "some-random-uid"],
                team=self.team,
                immediate=True,
            )
            _create_event(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val1"})
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(team=self.team, event="sign out", distinct_id="2", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(team=self.team, event="sign out", distinct_id="3", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(team=self.team, event="sign out", distinct_id="4", properties={"key": "test_val3"})
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(
                select=["event", "distinct_id", "properties.key", "'a%sd'", "concat(event, ' ', properties.key)"],
                properties=[
                    PersonPropertyFilter(
                        type="person", key="email", value="tom@posthog.com", operator=PropertyOperator.exact
                    )
                ],
            )
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(len(response["results"]), 2)

    def test_json_undefined_constant_error(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/query/?query=%7B%22kind%22%3A%22EventsQuery%22%2C%22select%22%3A%5B%22*%22%5D%2C%22limit%22%3AInfinity%7D"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Unsupported constant found in JSON: Infinity",
                "attr": None,
            },
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/query/?query=%7B%22kind%22%3A%22EventsQuery%22%2C%22select%22%3A%5B%22*%22%5D%2C%22limit%22%3ANaN%7D"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Unsupported constant found in JSON: NaN",
                "attr": None,
            },
        )

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
            _create_event(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val1"})
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(team=self.team, event="sign out", distinct_id="2", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(team=self.team, event="sign out", distinct_id="3", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team, event="sign out", distinct_id="4", properties={"key": "test_val3", "path": "a/b/c"}
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = EventsQuery(select=["properties.key", "count()"])
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(len(response["results"]), 3)

            query.where = ["count() > 1"]
            response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            self.assertEqual(len(response["results"]), 1)

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
            _create_event(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val1"})
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(team=self.team, event="sign out", distinct_id="2", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:12:00"):
            _create_event(team=self.team, event="sign out", distinct_id="3", properties={"key": "test_val2"})
        with freeze_time("2020-01-10 12:13:00"):
            _create_event(
                team=self.team, event="sign out", distinct_id="4", properties={"key": "test_val3", "path": "a/b/c"}
            )
        flush_persons_and_events()

        with freeze_time("2020-01-10 12:14:00"):
            query = HogQLQuery(query="select event, distinct_id, properties.key from events order by timestamp")
            api_response = self.client.post(f"/api/projects/{self.team.id}/query/", query.dict()).json()
            query.response = HogQLQueryResponse.parse_obj(api_response)

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
