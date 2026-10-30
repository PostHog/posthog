from posthog.test.base import QueryMatchingTest

from django.test import SimpleTestCase

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import Team


class TestMembershipSchema(QueryMatchingTest, SimpleTestCase):
    def test_membership_is_namespaced_and_team_guarded(self) -> None:
        database = Database()
        assert database.has_table(["posthog", "person_group_membership"])
        assert not database.has_table(["person_group_membership"])
        query = parse_select(
            "SELECT distinct_id FROM posthog.person_group_membership WHERE group_key = 'workspace-demo'"
        )
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
