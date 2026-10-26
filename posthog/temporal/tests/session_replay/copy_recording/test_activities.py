import re
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.test import override_settings

from asgiref.sync import async_to_sync
from parameterized import parameterized
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.session_recording_v2_service import RecordingBlock
from posthog.temporal.session_replay.copy_recording.activities import copy_session_recording
from posthog.temporal.session_replay.copy_recording.types import CopySessionInput, CopySessionResult

ACTIVITIES = "posthog.temporal.session_replay.copy_recording.activities"


@override_settings(SESSION_RECORDING_V2_S3_BUCKET="replay-bucket", SESSION_RECORDING_V2_S3_PREFIX="session_recordings")
class TestCopySessionRecording(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.target_team = Team.objects.create(organization=self.organization, name="Demo")
        self.start = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
        self.blocks = [
            RecordingBlock(
                key=f"session_recordings/30d/{i}-0000000000000000",
                start_byte=0,
                end_byte=9,
                start_timestamp=(self.start + timedelta(minutes=i)).isoformat(),
                end_timestamp=(self.start + timedelta(minutes=i, seconds=50)).isoformat(),
            )
            for i in range(2)
        ]
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            distinct_id="d1",
            first_timestamp=self.start,
            last_timestamp=self.start + timedelta(minutes=1, seconds=50),
            first_url="https://example.com/pricing",
            click_count=7,
            active_milliseconds=60_000,
            block_urls=[f"s3://replay-bucket/{b.key}?range=bytes=0-9" for b in self.blocks],
            block_first_timestamps=[datetime.fromisoformat(b.start_timestamp) for b in self.blocks],
            block_last_timestamps=[datetime.fromisoformat(b.end_timestamp) for b in self.blocks],
            ensure_analytics_event_in_session=False,
        )
        self.event_uuids = [
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="d1",
                timestamp=self.start + timedelta(seconds=10 * i),
                properties={"$session_id": "s1", "$current_url": "https://example.com/pricing"},
            )
            for i in range(3)
        ]
        flush_persons_and_events()

    def _run(self, target_team_id: int | None = None) -> tuple[CopySessionResult, MagicMock, AsyncMock]:
        client = MagicMock()
        client.fetch_block = AsyncMock(side_effect=lambda key, *_: f"plain-{key[-20:]}".encode())
        client.encrypt_blocks = AsyncMock(side_effect=lambda _s, _t, blocks, _r: [b"sealed:" + b for b in blocks])
        client_cm = MagicMock()
        client_cm.__aenter__ = AsyncMock(return_value=client)
        client_cm.__aexit__ = AsyncMock(return_value=None)
        upload = AsyncMock()
        with (
            patch(f"{ACTIVITIES}.fetch_blocks_from_recording_api", AsyncMock(return_value=self.blocks)),
            patch(f"{ACTIVITIES}.recording_api_client", return_value=client_cm),
            patch(f"{ACTIVITIES}._upload", upload),
        ):
            input = CopySessionInput(
                source_team_id=self.team.pk,
                target_team_id=target_team_id or self.target_team.pk,
                session_id="s1",
                retention_days=365,
            )
            result: CopySessionResult = async_to_sync(self._run_activity)(input)
        return result, client, upload

    async def _run_activity(self, input: CopySessionInput) -> CopySessionResult:
        return await ActivityEnvironment().run(copy_session_recording, input)

    @parameterized.expand([("fresh_target", 0), ("retry_after_partial_event_copy", 1)])
    def test_copies_recording_events_and_metadata_into_target_team(self, _: str, pre_copied_events: int) -> None:
        for uuid in self.event_uuids[:pre_copied_events]:
            _create_event(
                team=self.target_team,
                event_uuid=uuid,
                event="$pageview",
                distinct_id="d1",
                timestamp=self.start,
                properties={"$session_id": "s1"},
            )
        flush_persons_and_events()

        result, client, upload = self._run()

        expected_warnings = (
            [f"HogQL sees {pre_copied_events} of 3 copied events"]
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA
            else []
        )
        assert (result.status, result.block_count, result.event_count, result.warnings) == (
            "copied",
            2,
            3,
            expected_warnings,
        )
        client.encrypt_blocks.assert_awaited_once()
        assert client.encrypt_blocks.await_args.args[1] == self.target_team.pk

        assert upload.await_args is not None
        key, body = upload.await_args.args
        assert re.fullmatch(r"session_recordings/1y/\d+-[0-9a-f]{16}", key)
        metadata = SessionReplayEvents().get_metadata("s1", self.target_team)
        assert metadata is not None
        assert (metadata["first_url"], metadata["click_count"], metadata["active_seconds"]) == (
            "https://example.com/pricing",
            7,
            60,
        )
        assert metadata["retention_period_days"] == 365
        stored = [
            body[int(m.group(1)) : int(m.group(2)) + 1]
            for url in metadata["block_urls"]
            if (m := re.search(r"range=bytes=(\d+)-(\d+)", url))
        ]
        assert stored == [b"sealed:" + f"plain-{b.key[-20:]}".encode() for b in self.blocks]

    def test_rerun_after_copy_does_not_duplicate(self) -> None:
        self._run()
        result, client, upload = self._run()

        assert result.status == "already_copied"
        client.encrypt_blocks.assert_not_awaited()
        upload.assert_not_awaited()

    @parameterized.expand([("another_organization", True), ("missing_team", False)])
    def test_refuses_target_outside_the_source_organization(self, _: str, target_exists: bool) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        target_team_id = other_team.pk if target_exists else other_team.pk + 1000

        with self.assertRaises(ApplicationError) as error:
            self._run(target_team_id=target_team_id)

        assert error.exception.non_retryable
        assert SessionReplayEvents().get_metadata("s1", other_team) is None
