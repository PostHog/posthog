"""Tests for personhog person routing in query runners.

Verifies that personId lookups in EventsQueryRunner and
SessionsQueryRunner correctly route through personhog (both UUID and
integer PK paths) and produce the expected AST output.
"""

from typing import Optional, cast

from posthog.test.base import BaseTest

from posthog.schema import EventsQuery, SessionsQuery

from posthog.hogql import ast

from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.sessions_query_runner import SessionsQueryRunner
from posthog.personhog_client.fake_client import fake_personhog_client

UUID_A = "550e8400-e29b-41d4-a716-446655440000"


def _extract_person_distinct_ids_from_where(where: Optional[ast.Expr]) -> list[str]:
    """Extract distinct_id constants from the personId cityHash64 IN (...) filter."""
    assert isinstance(where, ast.And)
    for expr in where.exprs:
        if (
            isinstance(expr, ast.CompareOperation)
            and expr.op == ast.CompareOperationOp.In
            and isinstance(expr.left, ast.Call)
            and expr.left.name == "cityHash64"
            and isinstance(expr.right, ast.Tuple)
        ):
            return [cast(ast.Constant, cast(ast.Call, x).args[0]).value for x in expr.right.exprs]
    raise AssertionError(f"No personId cityHash64 IN filter found in WHERE: {where}")


class TestEventsQueryRunnerPersonhog(BaseTest):
    def test_uuid_person_id_expands_distinct_ids_via_personhog(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.pk,
                person_id=42,
                uuid=UUID_A,
                distinct_ids=["id1", "id2"],
            )

            query = EventsQuery(kind="EventsQuery", select=["*"], personId=UUID_A, orderBy=[])
            query_ast = EventsQueryRunner(query=query, team=self.team).to_query()

            ids = _extract_person_distinct_ids_from_where(query_ast.where)
            assert ids == ["id1", "id2"]
            fake.assert_called("get_person_by_uuid")
            fake.assert_called("get_distinct_ids_for_person")

    def test_uuid_person_id_not_found_returns_empty(self):
        with fake_personhog_client() as fake:
            query = EventsQuery(kind="EventsQuery", select=["*"], personId=UUID_A, orderBy=[])
            query_ast = EventsQueryRunner(query=query, team=self.team).to_query()

            ids = _extract_person_distinct_ids_from_where(query_ast.where)
            assert ids == []
            fake.assert_called("get_person_by_uuid")

    def test_non_uuid_person_id_routes_through_personhog(self):
        """Integer PK routes through get_person_by_id (personhog)."""
        from posthog.models import Person

        person = Person.objects.create(team=self.team, distinct_ids=["id1", "id2"])

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.pk,
                person_id=person.pk,
                uuid=str(person.uuid),
                distinct_ids=["id1", "id2"],
            )

            query = EventsQuery(kind="EventsQuery", select=["*"], personId=str(person.pk), orderBy=[])
            query_ast = EventsQueryRunner(query=query, team=self.team).to_query()

            ids = _extract_person_distinct_ids_from_where(query_ast.where)
            assert set(ids) == {"id1", "id2"}
            fake.assert_not_called("get_person_by_uuid")
            fake.assert_called("get_person")


class TestSessionsQueryRunnerPersonhog(BaseTest):
    def test_uuid_person_id_expands_distinct_ids_via_personhog(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.pk,
                person_id=42,
                uuid=UUID_A,
                distinct_ids=["id1", "id2"],
            )

            query = SessionsQuery(kind="SessionsQuery", select=["session_id"], personId=UUID_A)
            query_ast = SessionsQueryRunner(query=query, team=self.team).to_query()

            ids = _extract_person_distinct_ids_from_where(query_ast.where)
            assert ids == ["id1", "id2"]
            fake.assert_called("get_person_by_uuid")
            fake.assert_called("get_distinct_ids_for_person")

    def test_uuid_person_id_not_found_returns_empty(self):
        with fake_personhog_client() as fake:
            query = SessionsQuery(kind="SessionsQuery", select=["session_id"], personId=UUID_A)
            query_ast = SessionsQueryRunner(query=query, team=self.team).to_query()

            ids = _extract_person_distinct_ids_from_where(query_ast.where)
            assert ids == []
            fake.assert_called("get_person_by_uuid")
