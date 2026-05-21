from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from langchain_core.runnables import RunnableConfig

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tools.replay.get_session_recording import GetSessionRecordingTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


@freeze_time("2025-01-15T12:00:00Z")
class TestGetSessionRecordingTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")

    async def _create_tool(self, state: AssistantState | None = None):
        if state is None:
            state = AssistantState(messages=[])

        config: RunnableConfig = RunnableConfig()
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)

        tool = await GetSessionRecordingTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            config=config,
            context_manager=context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )
        return tool

    def _produce_replay(
        self,
        session_id: str | None = None,
        distinct_id: str = "user",
        first_timestamp: datetime | None = None,
        last_timestamp: datetime | None = None,
        first_url: str = "https://example.com",
        click_count: int = 0,
        keypress_count: int = 0,
        console_error_count: int = 0,
        active_milliseconds: float = 0,
    ) -> str:
        if session_id is None:
            session_id = str(uuid7())
        if first_timestamp is None:
            first_timestamp = datetime(2025, 1, 15, 10, 0, 0)
        if last_timestamp is None:
            last_timestamp = first_timestamp + timedelta(minutes=5)

        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            distinct_id=distinct_id,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            first_url=first_url,
            click_count=click_count,
            keypress_count=keypress_count,
            console_error_count=console_error_count,
            active_milliseconds=active_milliseconds,
            ensure_analytics_event_in_session=False,
        )
        return session_id

    async def test_returns_metadata_for_known_recording(self):
        session_id = self._produce_replay(
            distinct_id="alice_42",
            first_timestamp=datetime(2025, 1, 15, 10, 0, 0),
            last_timestamp=datetime(2025, 1, 15, 10, 5, 0),
            first_url="https://example.com/checkout",
            click_count=7,
            keypress_count=3,
            console_error_count=1,
            active_milliseconds=120000,
        )

        tool = await self._create_tool()
        result_text, artifact = await tool._arun_impl(session_id=session_id)

        self.assertIsNone(artifact)
        self.assertIn(session_id, result_text)
        self.assertIn("distinct_id: alice_42", result_text)
        self.assertIn("click_count: 7", result_text)
        self.assertIn("keypress_count: 3", result_text)
        self.assertIn("console_error_count: 1", result_text)
        self.assertIn("first_url: https://example.com/checkout", result_text)
        self.assertIn("duration: 5m 0s", result_text)

    async def test_returns_not_found_for_unknown_recording(self):
        tool = await self._create_tool()
        result_text, artifact = await tool._arun_impl(session_id="does-not-exist")

        self.assertIsNone(artifact)
        self.assertIn("No recording was found", result_text)
        self.assertIn("does-not-exist", result_text)

    async def test_rejects_empty_session_id(self):
        tool = await self._create_tool()
        result_text, artifact = await tool._arun_impl(session_id="   ")

        self.assertIsNone(artifact)
        self.assertIn("No session ID was provided", result_text)
