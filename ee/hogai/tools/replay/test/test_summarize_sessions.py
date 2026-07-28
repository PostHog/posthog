from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.test import override_settings

from langchain_core.runnables import RunnableConfig

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.session_summaries.availability import CLOUD_ONLY_MESSAGE
from ee.hogai.tools.replay.summarize_sessions import SummarizeSessionsTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


class TestSummarizeSessionsTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    async def _create_tool(self) -> SummarizeSessionsTool:
        state = AssistantState(messages=[])
        config: RunnableConfig = RunnableConfig()
        return await SummarizeSessionsTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            config=config,
            context_manager=AssistantContextManager(team=self.team, user=self.user, config=config),
            node_path=(NodePath(name="test_node", tool_call_id="test_tool_call_id", message_id="test"),),
        )

    async def test_off_cloud_explains_instead_of_starting_workflows(self):
        # A dispatch here fans out one activity per session, every one of which fails off-cloud,
        # so the tool has to answer the user directly instead of starting the group workflow.
        tool = await self._create_tool()

        with (
            override_settings(DEBUG=False, CLOUD_DEPLOYMENT=None),
            patch(
                "ee.hogai.tools.replay.summarize_sessions.execute_summarize_session_group",
                side_effect=AssertionError("should not dispatch a workflow off-cloud"),
            ),
        ):
            result_text, artifact = await tool._arun_impl(
                recordings_filters_or_explicit_session_ids=["session_1", "session_2"],
                summary_title="Test summary",
            )

        assert result_text == CLOUD_ONLY_MESSAGE
        assert artifact is None
