from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

SCORED = "SELECT toString(properties.report_id) AS report_id FROM events WHERE event = 'scored'"


def _branch(event: str, extra: str = "") -> str:
    return f"SELECT toString(properties.report_id) AS report_id, '{event}' AS kind FROM events WHERE event = '{event}' {extra}"


def _cte_query(op: str = "IN", second_branch_extra: str = "") -> str:
    return f"""
        WITH scored AS ({SCORED}),
        outcome_events AS ({_branch("opened")} UNION ALL {_branch("fixed", second_branch_extra)})
        SELECT kind, report_id FROM outcome_events
        WHERE report_id {op} (SELECT report_id FROM scored)
        ORDER BY kind, report_id
    """


class TestUnionGlobalInPushdownPrinting(BaseTest):
    def _print(self, query: str, use_new_events_schema: bool = True) -> str:
        context = HogQLContext(
            team_id=self.team.pk, enable_select_queries=True, use_new_events_schema=use_new_events_schema
        )
        return prepare_and_print_ast(parse_select(query), context, "clickhouse")[0]

    @parameterized.expand(
        [
            ("cte", _cte_query(), 2),
            ("cte_not_in", _cte_query(op="NOT IN"), 2),
            (
                "inline_union",
                f"SELECT kind FROM ({_branch('opened')} UNION ALL {_branch('fixed')}) AS outcome_events "
                f"WHERE report_id IN ({SCORED}) AND kind != ''",
                2,
            ),
            (
                "three_branches",
                f"SELECT kind FROM ({_branch('opened')} UNION ALL {_branch('acted')} UNION ALL {_branch('fixed')}) "
                f"WHERE report_id IN ({SCORED})",
                3,
            ),
        ]
    )
    def test_global_in_on_union_moves_into_each_branch(self, _name: str, query: str, branch_count: int) -> None:
        printed = self._print(query)
        assert printed.count("lobalIn(toString(") + printed.count("lobalNotIn(toString(") == branch_count, printed
        assert "lobalIn(outcome_events." not in printed and "lobalNotIn(outcome_events." not in printed, printed

    @parameterized.expand(
        [
            ("old_events_table", _cte_query(), False),
            ("branch_aggregates", _cte_query(second_branch_extra="GROUP BY report_id, kind"), True),
            ("branch_limits", _cte_query(second_branch_extra="LIMIT 1"), True),
        ]
    )
    def test_global_in_stays_on_union_when_pushdown_does_not_apply(
        self, _name: str, query: str, use_new_events_schema: bool
    ) -> None:
        printed = self._print(query, use_new_events_schema=use_new_events_schema)
        assert "globalIn(outcome_events.report_id" in printed, printed


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
class TestUnionGlobalInPushdownResults(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        for event, report_id in [
            ("scored", "r1"),
            ("scored", "r2"),
            ("opened", "r1"),
            ("opened", "r3"),
            ("fixed", "r2"),
            ("fixed", "r3"),
        ]:
            _create_event(event=event, distinct_id="user", team=self.team, properties={"report_id": report_id})
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("in", "IN", [("fixed", "r2"), ("opened", "r1")]),
            ("not_in", "NOT IN", [("fixed", "r3"), ("opened", "r3")]),
        ]
    )
    def test_pushdown_keeps_the_rows_of_every_branch(self, _name: str, op: str, expected: list) -> None:
        response = execute_hogql_query(
            _cte_query(op=op), team=self.team, modifiers=HogQLQueryModifiers(useNewEventsSchema=True)
        )
        assert response.clickhouse is not None and "events_json" in response.clickhouse
        assert response.results == expected
