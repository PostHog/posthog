"""Tests that personId lookups in EventsQueryRunner and SessionsQueryRunner
produce identical AST output via the ORM and personhog paths."""

from typing import Optional, cast

from posthog.test.base import BaseTest

from parameterized import parameterized_class

from posthog.schema import EventsQuery, SessionsQuery

from posthog.hogql import ast

from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.sessions_query_runner import SessionsQueryRunner
from posthog.personhog_client.test_helpers import PersonhogTestMixin

UUID_NONEXISTENT = "550e8400-e29b-41d4-a716-446655440000"


def _find_person_id_filter(where: Optional[ast.Expr]) -> ast.CompareOperation:
    """Find the personId cityHash64 IN (...) filter in the WHERE clause."""
    assert isinstance(where, ast.And)
    for expr in where.exprs:
        if (
            isinstance(expr, ast.CompareOperation)
            and expr.op == ast.CompareOperationOp.In
            and isinstance(expr.left, ast.Call)
            and expr.left.name == "cityHash64"
            and isinstance(expr.right, ast.Tuple)
        ):
            return expr
    raise AssertionError(f"No personId cityHash64 IN filter found in WHERE: {where}")


def _extract_person_distinct_ids_from_where(where: Optional[ast.Expr]) -> list[str]:
    """Extract distinct_id constants from the personId cityHash64 IN (...) filter."""
    expr = _find_person_id_filter(where)
    rhs = expr.right
    assert isinstance(rhs, ast.Tuple)
    return [cast(ast.Constant, cast(ast.Call, x).args[0]).value for x in rhs.exprs]


def _extract_distinct_id_field_chain(where: Optional[ast.Expr]) -> list[str | int]:
    """Extract the Field chain from inside cityHash64(...) in the personId filter."""
    expr = _find_person_id_filter(where)
    lhs = expr.left
    assert isinstance(lhs, ast.Call)
    assert len(lhs.args) == 1
    field = lhs.args[0]
    assert isinstance(field, ast.Field)
    return field.chain


@parameterized_class(("personhog",), [(False,), (True,)])
class TestEventsQueryRunnerPersonRouting(PersonhogTestMixin, BaseTest):
    def test_uuid_person_id_expands_distinct_ids(self):
        person = self._seed_person(team=self.team, distinct_ids=["id1", "id2"])

        query = EventsQuery(kind="EventsQuery", select=["*"], personId=str(person.uuid), orderBy=[])
        query_ast = EventsQueryRunner(query=query, team=self.team).to_query()

        ids = _extract_person_distinct_ids_from_where(query_ast.where)
        assert set(ids) == {"id1", "id2"}
        self._assert_personhog_called("get_person_by_uuid")
        self._assert_personhog_called("get_distinct_ids_for_person")

    def test_uuid_person_id_not_found_returns_empty(self):
        query = EventsQuery(kind="EventsQuery", select=["*"], personId=UUID_NONEXISTENT, orderBy=[])
        query_ast = EventsQueryRunner(query=query, team=self.team).to_query()

        ids = _extract_person_distinct_ids_from_where(query_ast.where)
        assert ids == []
        self._assert_personhog_called("get_person_by_uuid")

    def test_integer_person_id_expands_distinct_ids(self):
        person = self._seed_person(team=self.team, distinct_ids=["id1", "id2"])

        query = EventsQuery(kind="EventsQuery", select=["*"], personId=str(person.pk), orderBy=[])
        query_ast = EventsQueryRunner(query=query, team=self.team).to_query()

        ids = _extract_person_distinct_ids_from_where(query_ast.where)
        assert set(ids) == {"id1", "id2"}
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_called("get_person")

    def test_invalid_person_id_returns_empty(self):
        query = EventsQuery(kind="EventsQuery", select=["*"], personId="not-a-uuid-or-int", orderBy=[])
        query_ast = EventsQueryRunner(query=query, team=self.team).to_query()

        ids = _extract_person_distinct_ids_from_where(query_ast.where)
        assert ids == []
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_not_called("get_person")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestSessionsQueryRunnerPersonRouting(PersonhogTestMixin, BaseTest):
    def test_uuid_person_id_expands_distinct_ids(self):
        person = self._seed_person(team=self.team, distinct_ids=["id1", "id2"])

        query = SessionsQuery(kind="SessionsQuery", select=["session_id"], personId=str(person.uuid))
        query_ast = SessionsQueryRunner(query=query, team=self.team).to_query()

        ids = _extract_person_distinct_ids_from_where(query_ast.where)
        assert set(ids) == {"id1", "id2"}
        self._assert_personhog_called("get_person_by_uuid")
        self._assert_personhog_called("get_distinct_ids_for_person")

    def test_uuid_person_id_not_found_returns_empty(self):
        query = SessionsQuery(kind="SessionsQuery", select=["session_id"], personId=UUID_NONEXISTENT)
        query_ast = SessionsQueryRunner(query=query, team=self.team).to_query()

        ids = _extract_person_distinct_ids_from_where(query_ast.where)
        assert ids == []
        self._assert_personhog_called("get_person_by_uuid")

    def test_integer_person_id_expands_distinct_ids(self):
        person = self._seed_person(team=self.team, distinct_ids=["id1", "id2"])

        query = SessionsQuery(kind="SessionsQuery", select=["session_id"], personId=str(person.pk))
        query_ast = SessionsQueryRunner(query=query, team=self.team).to_query()

        ids = _extract_person_distinct_ids_from_where(query_ast.where)
        assert set(ids) == {"id1", "id2"}
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_called("get_person")

    def test_invalid_person_id_returns_empty(self):
        query = SessionsQuery(kind="SessionsQuery", select=["session_id"], personId="not-a-uuid-or-int")
        query_ast = SessionsQueryRunner(query=query, team=self.team).to_query()

        ids = _extract_person_distinct_ids_from_where(query_ast.where)
        assert ids == []
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_not_called("get_person")

    def test_person_join_qualifies_distinct_id_chain(self):
        person = self._seed_person(team=self.team, distinct_ids=["id1"])

        query_without_join = SessionsQuery(kind="SessionsQuery", select=["session_id"], personId=str(person.uuid))
        ast_without = SessionsQueryRunner(query=query_without_join, team=self.team).to_query()
        assert _extract_distinct_id_field_chain(ast_without.where) == ["distinct_id"]

    def test_person_join_qualifies_distinct_id_chain_with_person_select(self):
        person = self._seed_person(team=self.team, distinct_ids=["id1"])

        query_with_join = SessionsQuery(
            kind="SessionsQuery", select=["session_id", "person_display_name"], personId=str(person.uuid)
        )
        ast_with = SessionsQueryRunner(query=query_with_join, team=self.team).to_query()
        assert _extract_distinct_id_field_chain(ast_with.where) == ["sessions", "distinct_id"]
