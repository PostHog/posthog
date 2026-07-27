from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from django.utils.timezone import now

from langchain_core.runnables import RunnableConfig

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tools.replay.summarize_sessions import (
    NO_LINKED_EVENTS_MESSAGE,
    NO_RECORDINGS_MATCHED_MESSAGE,
    SummarizeSessionsTool,
)
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


@freeze_time("2025-01-15T12:00:00Z")
class TestSummarizeSessionsTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")

    async def _create_tool(self):
        config: RunnableConfig = RunnableConfig()
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        return await SummarizeSessionsTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=config,
            context_manager=context_manager,
            node_path=(NodePath(name="test_node", tool_call_id="test_tool_call_id", message_id="test"),),
        )

    async def test_recordings_without_linked_events_report_missing_events(self) -> None:
        # A recording exists but has no analytics events tagged with its $session_id, so it can't be summarized.
        base_time = (now() - timedelta(days=1)).replace(microsecond=0)
        produce_replay_summary(
            session_id="no_events_session",
            team_id=self.team.pk,
            first_timestamp=base_time,
            last_timestamp=base_time + timedelta(seconds=30),
            distinct_id="u_no_events",
            ensure_analytics_event_in_session=False,
        )
        tool = await self._create_tool()
        content, artifact = await tool._arun_impl(
            recordings_filters_or_explicit_session_ids=["no_events_session"],
            summary_title="",
        )
        assert content == NO_LINKED_EVENTS_MESSAGE
        assert artifact is None

    async def test_unknown_sessions_report_no_recordings_matched(self) -> None:
        tool = await self._create_tool()
        content, artifact = await tool._arun_impl(
            recordings_filters_or_explicit_session_ids=["does_not_exist"],
            summary_title="",
        )
        assert content == NO_RECORDINGS_MATCHED_MESSAGE
        assert artifact is None
