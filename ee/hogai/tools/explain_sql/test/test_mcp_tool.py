from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from posthog.hogql.cost.statistics import EventVolume, FixedStatisticsProvider

from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.explain_sql.mcp_tool import ExplainSQLMCPTool, ExplainSQLMCPToolArgs


class TestExplainSQLMCPTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = ExplainSQLMCPTool(team=self.team, user=self.user)
        self.provider = FixedStatisticsProvider(
            event_volume={self.team.pk: EventVolume(total=1_000_000, by_event={"$pageview": 1_000_000}, days=10)}
        )

    async def test_returns_the_plan_without_running_the_query(self):
        with (
            patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True),
            patch("posthog.hogql.metadata.ClickHouseStatisticsProvider", return_value=self.provider),
        ):
            result = await self.tool.execute(
                ExplainSQLMCPToolArgs(
                    query="SELECT count() FROM events WHERE timestamp > now() - interval 7 day AND timestamp < now()"
                )
            )

        assert result.content.startswith("Reads about 700,000 rows across 1 table(s).")
        assert "- Scan events, about 700K rows (7 days)" in result.content
        assert result.structured_content is not None
        estimate = result.structured_content["scan_estimate"]
        plan = result.structured_content["cost_plan"]
        assert isinstance(estimate, dict) and isinstance(plan, list)
        assert estimate["rows"] == 700_000
        assert [step["kind"] for step in plan if isinstance(step, dict)] == ["scan"]

    async def test_says_when_no_estimate_is_available(self):
        with patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=False):
            result = await self.tool.execute(ExplainSQLMCPToolArgs(query="SELECT 1"))

        assert result.content == "No estimate is available for this query. It is valid and can be run."

    async def test_rejects_an_invalid_query_with_the_error(self):
        with self.assertRaises(MaxToolRetryableError) as raised:
            await self.tool.execute(ExplainSQLMCPToolArgs(query="SELECT count() FROM no_such_table"))

        assert "no_such_table" in str(raised.exception)
