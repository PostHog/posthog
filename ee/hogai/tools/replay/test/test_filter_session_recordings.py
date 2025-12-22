from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import (
    MaxInnerUniversalFiltersGroup,
    MaxOuterUniversalFiltersGroup,
    MaxRecordingUniversalFilters,
    PropertyOperator,
    RecordingDurationFilter,
)

from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, Team
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tools.replay.filter_session_recordings import FilterSessionRecordingsTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


@freeze_time("2025-01-15T12:00:00Z")
class TestFilterSessionRecordingsTool(ClickhouseTestMixin, NonAtomicBaseTest):
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

        tool = await FilterSessionRecordingsTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=state,
            config=config,
            context_manager=context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )
        return tool

    def _create_empty_filters(self, date_from: str = "-7d") -> MaxRecordingUniversalFilters:
        return MaxRecordingUniversalFilters(
            filter_group=MaxOuterUniversalFiltersGroup(
                type="AND",
                values=[MaxInnerUniversalFiltersGroup(type="AND", values=[])],
            ),
            duration=[],
            date_from=date_from,
        )

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
        team_id: int | None = None,
    ):
        if session_id is None:
            session_id = str(uuid7())
        if first_timestamp is None:
            first_timestamp = datetime(2025, 1, 15, 10, 0, 0)
        if last_timestamp is None:
            last_timestamp = first_timestamp + timedelta(minutes=5)

        produce_replay_summary(
            team_id=team_id or self.team.pk,
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

    async def test_returns_no_recordings_message_when_none_found(self):
        tool = await self._create_tool()
        filters = self._create_empty_filters()

        result_text, artifact = await tool._arun_impl(recordings_filters=filters)

        self.assertIn("No recordings found", result_text)
        self.assertIsNone(artifact)

    async def test_returns_single_recording_with_metadata(self):
        base_time = datetime(2025, 1, 15, 10, 0, 0)
        self._produce_replay(
            distinct_id="user_1",
            first_timestamp=base_time,
            last_timestamp=base_time + timedelta(minutes=5),
            first_url="https://example.com/page1",
            click_count=10,
            keypress_count=5,
            console_error_count=2,
            active_milliseconds=120000,
        )

        tool = await self._create_tool()
        filters = self._create_empty_filters()

        result_text, artifact = await tool._arun_impl(recordings_filters=filters)

        self.assertIn("Found 1 recording", result_text)
        self.assertIn("User: user_1", result_text)
        self.assertIn("https://example.com/page1", result_text)
        self.assertIn("10 clicks", result_text)
        self.assertIn("5 keypresses", result_text)
        self.assertIn("Console errors: 2", result_text)
        self.assertIsNone(artifact)

    async def test_returns_multiple_recordings_formatted(self):
        base_time = datetime(2025, 1, 15, 10, 0, 0)
        for i in range(3):
            self._produce_replay(
                distinct_id=f"user_{i}",
                first_timestamp=base_time + timedelta(hours=i),
                last_timestamp=base_time + timedelta(hours=i, minutes=10),
                first_url=f"https://example.com/page{i}",
                click_count=i * 5,
            )

        tool = await self._create_tool()
        filters = self._create_empty_filters()

        result_text, artifact = await tool._arun_impl(recordings_filters=filters)

        self.assertIn("Found 3 recordings", result_text)
        self.assertIn("1.", result_text)
        self.assertIn("2.", result_text)
        self.assertIn("3.", result_text)
        self.assertIsNone(artifact)

    async def test_limits_displayed_recordings_to_5(self):
        base_time = datetime(2025, 1, 15, 5, 0, 0)  # Start at 5am so all 7 are before 12pm
        for i in range(7):
            self._produce_replay(
                distinct_id=f"user_{i}",
                first_timestamp=base_time + timedelta(hours=i),
                last_timestamp=base_time + timedelta(hours=i, minutes=10),
            )

        tool = await self._create_tool()
        filters = self._create_empty_filters()

        result_text, artifact = await tool._arun_impl(recordings_filters=filters)

        self.assertIn("Found 7 recordings", result_text)
        self.assertIn("...and 2 more recordings", result_text)
        self.assertIn("1.", result_text)
        self.assertIn("5.", result_text)
        self.assertNotIn("6.", result_text)
        self.assertIsNone(artifact)

    async def test_filters_by_duration(self):
        base_time = datetime(2025, 1, 15, 10, 0, 0)
        self._produce_replay(
            distinct_id="user_short",
            first_timestamp=base_time,
            last_timestamp=base_time + timedelta(seconds=30),
        )
        self._produce_replay(
            distinct_id="user_long",
            first_timestamp=base_time + timedelta(hours=1),
            last_timestamp=base_time + timedelta(hours=1, minutes=10),
        )

        tool = await self._create_tool()
        filters = MaxRecordingUniversalFilters(
            filter_group=MaxOuterUniversalFiltersGroup(
                type="AND",
                values=[MaxInnerUniversalFiltersGroup(type="AND", values=[])],
            ),
            duration=[
                RecordingDurationFilter(
                    key="duration",
                    type="recording",
                    operator=PropertyOperator.GT,
                    value=300,
                )
            ],
            date_from="-7d",
        )

        result_text, artifact = await tool._arun_impl(recordings_filters=filters)

        self.assertIn("Found 1 recording", result_text)
        self.assertIn("user_long", result_text)
        self.assertNotIn("user_short", result_text)
        self.assertIsNone(artifact)

    async def test_excludes_recordings_from_other_teams(self):
        from asgiref.sync import sync_to_async

        @sync_to_async
        def create_other_team():
            other_org = Organization.objects.create(name="Other Org")
            return Team.objects.create(organization=other_org, name="Other Team")

        other_team = await create_other_team()

        base_time = datetime(2025, 1, 15, 10, 0, 0)
        self._produce_replay(
            distinct_id="our_user",
            first_timestamp=base_time,
            last_timestamp=base_time + timedelta(minutes=5),
        )
        self._produce_replay(
            distinct_id="other_user",
            first_timestamp=base_time,
            last_timestamp=base_time + timedelta(minutes=5),
            team_id=other_team.pk,
        )

        tool = await self._create_tool()
        filters = self._create_empty_filters()

        result_text, artifact = await tool._arun_impl(recordings_filters=filters)

        self.assertIn("Found 1 recording", result_text)
        self.assertIn("our_user", result_text)
        self.assertNotIn("other_user", result_text)
        self.assertIsNone(artifact)

    @parameterized.expand(
        [
            (timedelta(hours=1, minutes=30, seconds=45), "1h", "30m"),
            (timedelta(minutes=5, seconds=30), "5m", "30s"),
            (timedelta(seconds=45), "45s", None),
        ]
    )
    async def test_formats_duration_correctly(
        self, duration: timedelta, expected_part_1: str, expected_part_2: str | None
    ):
        base_time = datetime(2025, 1, 15, 10, 0, 0)
        self._produce_replay(
            distinct_id="user_1",
            first_timestamp=base_time,
            last_timestamp=base_time + duration,
        )

        tool = await self._create_tool()
        filters = self._create_empty_filters()

        result_text, artifact = await tool._arun_impl(recordings_filters=filters)

        self.assertIn("Duration:", result_text)
        self.assertIn(expected_part_1, result_text)
        if expected_part_2:
            self.assertIn(expected_part_2, result_text)
        self.assertIsNone(artifact)


class TestFilterSessionRecordingsToolFormatting(NonAtomicBaseTest):
    """Tests for formatting logic that don't need ClickHouse."""

    def test_format_recording_metadata_with_all_fields(self):
        from ee.hogai.tools.replay.filter_session_recordings import FilterSessionRecordingsTool

        tool = FilterSessionRecordingsTool(team=self.team, user=self.user)
        recording = {
            "distinct_id": "test_user",
            "start_time": datetime(2025, 1, 15, 10, 30, 0),
            "duration": 3665,  # 1h 1m 5s
            "click_count": 42,
            "keypress_count": 100,
            "console_error_count": 3,
            "active_seconds": 1800,
            "inactive_seconds": 1865,
            "first_url": "https://app.posthog.com/dashboard",
            "ongoing": False,
        }

        result = tool._format_recording_metadata(recording)

        self.assertIn("User: test_user", result)
        self.assertIn("Started: 2025-01-15 10:30:00 UTC", result)
        self.assertIn("Duration: 1h 1m 5s", result)
        self.assertIn("42 clicks", result)
        self.assertIn("100 keypresses", result)
        self.assertIn("Console errors: 3", result)
        self.assertIn("Active: 1800s", result)
        self.assertIn("Inactive: 1865s", result)
        self.assertIn("First URL: https://app.posthog.com/dashboard", result)

    def test_format_recording_metadata_ongoing_session(self):
        from ee.hogai.tools.replay.filter_session_recordings import FilterSessionRecordingsTool

        tool = FilterSessionRecordingsTool(team=self.team, user=self.user)
        recording = {
            "distinct_id": "live_user",
            "ongoing": True,
        }

        result = tool._format_recording_metadata(recording)

        self.assertIn("Status: Ongoing", result)

    def test_format_recording_metadata_minimal_fields(self):
        from ee.hogai.tools.replay.filter_session_recordings import FilterSessionRecordingsTool

        tool = FilterSessionRecordingsTool(team=self.team, user=self.user)
        recording = {
            "distinct_id": "minimal_user",
        }

        result = tool._format_recording_metadata(recording)

        self.assertEqual(result, "User: minimal_user")
