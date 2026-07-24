from posthog.test.base import BaseTest

from posthog.schema import RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.session_recordings.queries.sub_queries.events_subquery import ReplayFiltersEventsSubQuery


class _SessionIdGroupKeyCollector(TraversingVisitor):
    def __init__(self) -> None:
        self.group_keys: list[ast.Expr] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.group_by:
            # $session_id is always the first group-by key in the matching-events queries
            self.group_keys.append(node.group_by[0])
        super().visit_select_query(node)


class TestMatchingEventsSubQuery(BaseTest):
    def test_session_id_group_key_is_aliased_across_global_in_boundary(self) -> None:
        # Grouping directly by properties.$session_id makes the ClickHouse analyzer name the group-by
        # key after the `$session_id` materialized read, which is quoted inconsistently across the
        # GlobalIn Remote boundary and 500s (NOT_FOUND_COLUMN_IN_BLOCK) on distributed ClickHouse.
        # Every session-id group key in the matching-events query — the outer query and each GlobalIn
        # subquery — must therefore be aliased so it crosses the boundary as a plain identifier.
        query = RecordingsQuery(
            kind="RecordingsQuery",
            events=[{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}],
        )

        ast_query = ReplayFiltersEventsSubQuery(team=self.team, query=query).get_query_for_event_id_matching()

        collector = _SessionIdGroupKeyCollector()
        collector.visit(ast_query)

        # the outer query plus at least one GlobalIn subquery both group by session_id
        assert len(collector.group_keys) >= 2
        for group_key in collector.group_keys:
            assert isinstance(group_key, ast.Alias)
            assert group_key.alias == "session_id"
            assert isinstance(group_key.expr, ast.Field)
            assert group_key.expr.chain == ["properties", "$session_id"]
