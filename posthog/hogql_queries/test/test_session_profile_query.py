from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import SessionTableVersion

from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast


class TestSessionProfileQuery(ClickhouseTestMixin, APIBaseTest):
    def _print_session_v3_query(self, query: str) -> str:
        modifiers = create_default_modifiers_for_team(self.team)
        modifiers.sessionTableVersion = SessionTableVersion.V3
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        prepared_ast = prepare_ast_for_printing(node=parse_select(query), context=context, dialect="clickhouse")
        if prepared_ast is None:
            return ""
        return print_prepared_ast(prepared_ast, context=context, dialect="clickhouse", pretty=True)

    def test_session_profile_point_query_v3(self):
        actual = self._print_session_v3_query(
            """
SELECT
    session_id,
    distinct_id,
    $start_timestamp,
    $end_timestamp,
    $entry_current_url,
    $session_duration,
    $channel_type,
    $is_bounce
FROM sessions
WHERE session_id = '019c2a52-6519-772d-b99a-60ba7cc4e266'
LIMIT 1
"""
        )
        assert self.generalize_sql(actual) == self.snapshot
