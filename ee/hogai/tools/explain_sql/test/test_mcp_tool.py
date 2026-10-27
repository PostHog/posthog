from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.cost.statistics import EventVolume, FixedStatisticsProvider

from ee.hogai.tool_errors import MaxToolAccessDeniedError, MaxToolRetryableError
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

        assert result.content.startswith("Reads about 700,000 rows from one table.")
        assert "- Scan events, about 700K rows (7 days)" in result.content
        assert result.structured_content is not None
        estimate = result.structured_content["scan_estimate"]
        plan = result.structured_content["cost_plan"]
        assert isinstance(estimate, dict) and isinstance(plan, list)
        assert estimate["rows"] == 700_000
        assert [step["kind"] for step in plan if isinstance(step, dict)] == ["scan"]

    async def test_headline_names_the_tables_it_could_not_estimate(self):
        with (
            patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True),
            patch("posthog.hogql.metadata.ClickHouseStatisticsProvider", return_value=self.provider),
        ):
            result = await self.tool.execute(
                ExplainSQLMCPToolArgs(query="SELECT count() FROM events e JOIN persons p ON p.id = e.person_id")
            )

        assert result.content.startswith("Reads about 36,500,000 rows from 1 of 2 tables. Not sized: persons.")
        assert result.content.endswith("Narrow the timestamp range or the event names to read less.")

    async def test_advice_for_a_sized_table_does_not_mention_events(self):
        provider = FixedStatisticsProvider(table_rows={(self.team.pk, "person"): 812_000})
        with (
            patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True),
            patch("posthog.hogql.metadata.ClickHouseStatisticsProvider", return_value=provider),
        ):
            result = await self.tool.execute(
                ExplainSQLMCPToolArgs(query="SELECT count() FROM persons WHERE properties.plan = 'pro'")
            )

        assert result.content.startswith("Reads up to 812,000 rows from one table.")
        assert result.content.endswith("and a selective filter may read less.")
        assert "event names" not in result.content

    async def test_denies_a_member_without_query_access(self):
        with patch("ee.hogai.tools.explain_sql.mcp_tool.UserAccessControl") as access_control:
            access_control.return_value.check_access_level_for_resource.return_value = False
            with self.assertRaises(MaxToolAccessDeniedError):
                await self.tool.execute(ExplainSQLMCPToolArgs(query="SELECT count() FROM events"))

    async def test_says_when_estimates_are_not_enabled_for_the_project(self):
        with patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=False):
            result = await self.tool.execute(ExplainSQLMCPToolArgs(query="SELECT count() FROM events"))

        assert result.content == "Scan estimates are not enabled for this project. The query is valid and can be run."

    @parameterized.expand(
        [
            ("no_table", "SELECT 1", "This query reads no table, so there is nothing to estimate."),
            (
                "table_only_in_a_subquery",
                "SELECT (SELECT count() FROM events)",
                "This query reads tables only inside a subquery outside FROM, which the estimate does not cover.",
            ),
        ]
    )
    async def test_tells_no_table_apart_from_a_table_the_estimate_does_not_cover(self, _name, query, expected):
        with patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True):
            result = await self.tool.execute(ExplainSQLMCPToolArgs(query=query))

        assert result.content == f"{expected} It is valid and can be run."

    async def test_says_when_the_estimate_is_unavailable(self):
        with (
            patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True),
            patch("posthog.hogql.metadata.estimate_scan", side_effect=RuntimeError("statistics down")),
        ):
            result = await self.tool.execute(ExplainSQLMCPToolArgs(query="SELECT count() FROM events"))

        assert result.content == "The cost of this query could not be estimated. It is valid and can be run."

    async def test_a_read_the_estimate_does_not_cover_is_called_out(self):
        with (
            patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True),
            patch("posthog.hogql.metadata.ClickHouseStatisticsProvider", return_value=self.provider),
        ):
            result = await self.tool.execute(
                ExplainSQLMCPToolArgs(query="SELECT count() FROM events WHERE person_id IN (SELECT id FROM persons)")
            )

        assert result.content.startswith(
            "Reads about 36,500,000 rows from one table.\nA subquery outside FROM reads more that is not counted."
        )

    async def test_rejects_an_invalid_query_with_the_error(self):
        with self.assertRaises(MaxToolRetryableError) as raised:
            await self.tool.execute(ExplainSQLMCPToolArgs(query="SELECT count() FROM no_such_table"))

        assert "no_such_table" in str(raised.exception)
