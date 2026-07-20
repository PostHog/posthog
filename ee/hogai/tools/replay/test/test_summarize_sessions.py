from datetime import datetime

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig

from posthog.exceptions import ClickHouseAtCapacity

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolTransientError
from ee.hogai.tools.replay.summarize_sessions import SummarizeSessionsTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


class TestSummarizeSessionsTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    async def _create_tool(self) -> SummarizeSessionsTool:
        config: RunnableConfig = RunnableConfig()
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        return await SummarizeSessionsTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=config,
            context_manager=context_manager,
            node_path=(NodePath(name="test_node", tool_call_id="test", message_id="test"),),
        )

    async def test_retries_capacity_error_then_succeeds(self):
        tool = await self._create_tool()
        bounds = (datetime(2025, 1, 1), datetime(2025, 1, 2))
        with (
            patch.object(
                SummarizeSessionsTool._find_sessions_timestamps_with_retry.retry,  # type: ignore[attr-defined]
                "sleep",
                lambda *a, **k: None,
            ),
            patch(
                "ee.hogai.tools.replay.summarize_sessions.find_sessions_timestamps",
                side_effect=[ClickHouseAtCapacity(), ClickHouseAtCapacity(), bounds],
            ) as mock_find,
        ):
            result = tool._find_sessions_timestamps_with_retry(["s1"])
        assert result == bounds
        assert mock_find.call_count == 3

    async def test_exhausted_capacity_degrades_to_transient_error(self):
        tool = await self._create_tool()
        with patch.object(tool, "_find_sessions_timestamps_with_retry", side_effect=ClickHouseAtCapacity()):
            with self.assertRaises(MaxToolTransientError):
                await tool._summarize_sessions_as_group(session_ids=["s1", "s2"], summary_title="t")
