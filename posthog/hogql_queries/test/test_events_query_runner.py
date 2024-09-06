from typing import Any, cast

from freezegun import freeze_time

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models import Person, Team
from posthog.models.organization import Organization
from posthog.schema import (
    CachedEventsQueryResponse,
    EventsQuery,
    EventPropertyFilter,
    PropertyOperator,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
)


class TestEventsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_events(self, data: list[tuple[str, str, Any]], event="$pageview"):
        person_result = []
        for distinct_id, timestamp, event_properties in data:
            with freeze_time(timestamp):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[distinct_id],
                        properties={
                            "name": distinct_id,
                        },
                    )
                )
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
        right_expr = cast(ast.Constant, where_expr.right)
        self.assertEqual(right_expr.value, ["id1", "id2"])

        # another team
        another_team = Team.objects.create(organization=Organization.objects.create())
        query_ast = EventsQueryRunner(query=query, team=another_team).to_query()
        where_expr = cast(ast.CompareOperation, cast(ast.And, query_ast.where).exprs[0])
        right_expr = cast(ast.Constant, where_expr.right)
        self.assertEqual(right_expr.value, [])

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

            assert response.results[0][0]["properties"]["bigInt"] == float(BIG_INT)
