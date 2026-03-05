from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from ee.hogai.session_summaries.tests.conftest import get_mock_enriched_llm_json_response
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.replay.mcp_tool import SummarizeSessionMCPTool, SummarizeSessionMCPToolArgs

MOCK_SESSION_ID = "00000000-0000-0000-0001-000000000000"


class TestSummarizeSessionMCPTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = SummarizeSessionMCPTool(team=self.team, user=self.user)

    def test_tool_name_and_schema(self):
        self.assertEqual(self.tool.name, "summarize_session")
        self.assertIsNotNone(self.tool.args_schema)
        validated = self.tool.args_schema.model_validate({"session_id": MOCK_SESSION_ID})
        self.assertEqual(validated.session_id, MOCK_SESSION_ID)

    @patch(
        "ee.hogai.tools.replay.mcp_tool.execute_summarize_session",
        new_callable=AsyncMock,
    )
    @patch("ee.hogai.tools.replay.mcp_tool.SummarizeSessionMCPTool._check_session_exists")
    async def test_successful_summarization(self, mock_exists, mock_summarize):
        mock_exists.return_value = True
        mock_summary = get_mock_enriched_llm_json_response(MOCK_SESSION_ID)
        mock_summarize.return_value = mock_summary

        content = await self.tool.execute(SummarizeSessionMCPToolArgs(session_id=MOCK_SESSION_ID))

        self.assertIn("Session", content)
        self.assertIn("Example Segment", content)
        self.assertIn("Another Example Segment", content)
        self.assertIn("Success", content)
        mock_summarize.assert_called_once_with(
            session_id=MOCK_SESSION_ID,
            user=self.user,
            team=self.team,
            model_to_use="o3",
        )

    @patch("ee.hogai.tools.replay.mcp_tool.SummarizeSessionMCPTool._check_session_exists")
    async def test_session_not_found(self, mock_exists):
        mock_exists.return_value = False

        with self.assertRaises(MaxToolRetryableError) as ctx:
            await self.tool.execute(SummarizeSessionMCPToolArgs(session_id="nonexistent-session"))

        self.assertIn("No session recording found", str(ctx.exception))

    @parameterized.expand([("",), ("  ",)])
    async def test_empty_session_id(self, session_id):
        with self.assertRaises(MaxToolRetryableError) as ctx:
            await self.tool.execute(SummarizeSessionMCPToolArgs(session_id=session_id))

        self.assertIn("must not be empty", str(ctx.exception))

    @patch(
        "ee.hogai.tools.replay.mcp_tool.execute_summarize_session",
        new_callable=AsyncMock,
        side_effect=ValueError("LLM generation failed"),
    )
    @patch("ee.hogai.tools.replay.mcp_tool.SummarizeSessionMCPTool._check_session_exists")
    async def test_summarization_failure(self, mock_exists, mock_summarize):
        mock_exists.return_value = True

        with self.assertRaises(MaxToolFatalError) as ctx:
            await self.tool.execute(SummarizeSessionMCPToolArgs(session_id=MOCK_SESSION_ID))

        self.assertIn("Failed to summarize session", str(ctx.exception))

    @patch(
        "ee.hogai.tools.replay.mcp_tool.execute_summarize_session",
        new_callable=AsyncMock,
    )
    @patch("ee.hogai.tools.replay.mcp_tool.SummarizeSessionMCPTool._check_session_exists")
    async def test_session_id_is_stripped(self, mock_exists, mock_summarize):
        mock_exists.return_value = True
        mock_summarize.return_value = get_mock_enriched_llm_json_response(MOCK_SESSION_ID)

        await self.tool.execute(SummarizeSessionMCPToolArgs(session_id=f"  {MOCK_SESSION_ID}  "))

        mock_summarize.assert_called_once_with(
            session_id=MOCK_SESSION_ID,
            user=self.user,
            team=self.team,
            model_to_use="o3",
        )
