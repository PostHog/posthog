from posthog.test.base import QueryMatchingTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.person_group_membership import PersonGroupMembershipTable
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.visitor import clone_expr

from posthog.models import Team


class TestMembershipSchema(QueryMatchingTest, SimpleTestCase):
    def test_membership_is_namespaced_and_team_guarded(self) -> None:
        database = Database()
        assert not database.has_table(["posthog", "person_group_membership"])
        assert not database.has_table(["person_group_membership"])
        query = parse_select(
            "SELECT distinct_id FROM posthog.person_group_membership WHERE group_key = 'workspace-demo'"
        )
        assert isinstance(query, ast.SelectQuery) and query.select_from is not None
        query.select_from.table_schema = PersonGroupMembershipTable()
        query = clone_expr(query, clear_types=True)
        context = HogQLContext(
            team_id=123,
            team=Team(id=123, project_id=123),
            database=database,
            enable_select_queries=True,
            restricted_properties=set(),
            use_new_events_schema=False,
        )
        sql, _ = prepare_and_print_ast(query, context=context, dialect="clickhouse")
        self.assertQueryMatchesSnapshot(sql)
        assert "team_id" in sql
        assert "person_group_membership.team_id, 123" in sql

    @parameterized.expand([("person_group_membership",), ("posthog.person_group_membership",)])
    def test_membership_cannot_be_queried_by_name(self, table: str) -> None:
        context = HogQLContext(
            team_id=123,
            database=Database(),
            enable_select_queries=True,
            restricted_properties=set(),
        )
        with self.assertRaises(QueryError):
            prepare_and_print_ast(parse_select(f"SELECT distinct_id FROM {table}"), context, "clickhouse")
