from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.hogql.query import execute_hogql_query

from products.ai_observability.backend.queries import get_tools_query


class TestToolsQuery(ClickhouseTestMixin, APIBaseTest):
    def _generation(self, minutes_ago: int, **properties: object) -> None:
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user",
            properties={"$ai_trace_id": "trace", **properties},
            timestamp=datetime.now(tz=UTC) - timedelta(minutes=minutes_ago),
        )

    def _tools(self) -> dict[str, dict]:
        flush_persons_and_events()
        query = get_tools_query().replace("{filters}", f"team_id = {self.team.pk}")
        response = execute_hogql_query(query=query, team=self.team)
        return {row[0]: dict(zip(response.columns or [], row)) for row in response.results}

    def test_failure_rate_counts_results_from_the_next_generation(self) -> None:
        self._generation(4, **{"$ai_tool_results": "lookup_order"})
        self._generation(
            3,
            **{"$ai_tools_called": "lookup_order,issue_refund"},
        )
        self._generation(
            2,
            **{
                "$ai_tool_results": "lookup_order,issue_refund",
                "$ai_tool_errors": "issue_refund",
                "$ai_tools_called": "issue_refund",
            },
        )
        self._generation(1, **{"$ai_tool_results": "issue_refund", "$ai_tool_errors": "issue_refund"})
        self._generation(1, **{"$ai_tools_called": "send_email,send_email", "$ai_tools_unknown": "send_email"})
        self._generation(1, **{"$ai_tool_results": "check_stock", "$ai_tool_errors": "check_stock"})
        self._generation(1)
        self._generation(1, **{"$ai_tools_called": "", "$ai_tool_results": ""})

        tools = self._tools()

        assert {
            name: (t["total_calls"], t["results"], t["failures"], t["failure_pct"]) for name, t in tools.items()
        } == {
            "lookup_order": (1, 2, 0, 0),
            "issue_refund": (2, 2, 2, 100),
            "send_email": (2, 0, 0, None),
            "check_stock": (0, 1, 1, 100),
        }
        assert tools["send_email"]["undefined_calls"] == 2
        assert tools["lookup_order"]["undefined_calls"] == 0
        assert tools["lookup_order"]["first_seen"] == tools["lookup_order"]["last_seen"]
        assert tools["lookup_order"]["first_seen"] == tools["issue_refund"]["first_seen"]
        assert tools["issue_refund"]["first_seen"] < tools["issue_refund"]["last_seen"]
        assert tools["check_stock"]["single_pct"] is None
        assert tools["check_stock"]["first_seen"] is None
        assert tools["check_stock"]["last_seen"] is None
        assert tools["check_stock"]["users"] == 0
        assert tools["check_stock"]["traces"] == 0
        assert tools["check_stock"]["days_seen"] == 0
