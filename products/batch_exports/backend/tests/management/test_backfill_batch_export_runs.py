import asyncio
import logging
from datetime import UTC, datetime, timedelta
from io import StringIO
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

import temporalio.client
from asgiref.sync import async_to_sync
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.test_utils import start_test_worker
from posthog.temporal.tests.utils.models import create_batch_export

from products.batch_exports.backend.management.commands.backfill_batch_export_runs import (
    find_missing_intervals,
    get_batch_exports,
)
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination, BatchExportRun
from products.batch_exports.backend.temporal import ACTIVITIES, WORKFLOWS

COMMAND_MODULE = "products.batch_exports.backend.management.commands.backfill_batch_export_runs"


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org")


@pytest.fixture
def team(org):
    return Team.objects.create(organization=org, name="Test Team")


def create_export(
    team, interval="hour", interval_offset=None, paused=False, destination_type="S3", tz="UTC", model=None
):
    destination = BatchExportDestination.objects.create(type=destination_type, config={})
    return BatchExport.objects.create(
        team=team,
        name=f"Test Export {uuid4()}",
        destination=destination,
        interval=interval,
        interval_offset=interval_offset,
        paused=paused,
        timezone=tz,
        model=model,
    )


def create_run(export, interval_start, interval_end, status=BatchExportRun.Status.COMPLETED):
    return BatchExportRun.objects.create(
        batch_export=export,
        data_interval_start=interval_start,
        data_interval_end=interval_end,
        status=status,
    )


def lookback(hours: int):
    """Return (start, end) for a lookback window ending at now."""
    now = timezone.now()
    return now - timedelta(hours=hours), now


class TestGetBatchExports:
    def test_no_exports_returns_empty(self, team):
        assert get_batch_exports() == []

    def test_paused_exports_are_excluded(self, team):
        export = create_export(team, paused=True)
        assert get_batch_exports() == []
        assert get_batch_exports(batch_export_id=str(export.id)) == []

    def test_deleted_exports_are_excluded(self, team):
        export = create_export(team)
        export.deleted = True
        export.save()
        assert get_batch_exports() == []
        assert get_batch_exports(batch_export_id=str(export.id)) == []

    def test_filter_by_destination_type(self, team):
        s3_export = create_export(team, destination_type="S3")
        create_export(team, destination_type="Databricks")

        results = get_batch_exports()
        assert len(results) == 2

        results = get_batch_exports(destination_type="S3")
        assert len(results) == 1
        assert results[0].id == s3_export.id

    def test_filter_by_batch_export_id(self, team):
        export1 = create_export(team)
        create_export(team)

        results = get_batch_exports(batch_export_id=str(export1.id))
        assert len(results) == 1
        assert results[0].id == export1.id

    def test_filter_by_model(self, team):
        events_export = create_export(team, model="events")
        create_export(team, model="persons")

        results = get_batch_exports(model="events")
        assert len(results) == 1
        assert results[0].id == events_export.id

    def test_nonexistent_batch_export_id_returns_empty(self, team):
        assert get_batch_exports(batch_export_id=str(uuid4())) == []


@freeze_time("2026-03-15 12:00:00")
class TestFindMissingIntervals:
    def test_no_exports_returns_empty(self, team):
        assert find_missing_intervals([], *lookback(24)) == []

    def test_fully_covered_hourly_export(self, team):
        export = create_export(team, interval="hour")
        now = timezone.now()
        for i in range(6, 0, -1):
            create_run(export, now - timedelta(hours=i), now - timedelta(hours=i - 1))

        assert find_missing_intervals([export], *lookback(6)) == []

    def test_detects_missing_hourly_runs(self, team):
        export = create_export(team, interval="hour")
        now = timezone.now()  # 2026-03-15 12:00:00

        # Create runs for hours 6-12, but skip hours 9 and 10
        for i in range(6, 0, -1):
            end = now - timedelta(hours=i - 1)
            if end.hour in (9, 10):
                continue
            create_run(export, now - timedelta(hours=i), end)

        results = find_missing_intervals([export], *lookback(6))
        assert len(results) == 1
        batch_export, missing = results[0]
        assert batch_export.id == export.id
        # Hours 9 and 10 are continuous, so they merge into one interval
        assert len(missing) == 1
        merged_start, merged_end = missing[0]
        assert merged_start.hour == 8
        assert merged_end.hour == 10

    def test_non_continuous_gaps_stay_separate(self, team):
        export = create_export(team, interval="hour")
        now = timezone.now()  # 2026-03-15 12:00:00

        # Create runs for hours ending 6-12, but skip hours 8 and 11
        for i in range(6, 0, -1):
            end = now - timedelta(hours=i - 1)
            if end.hour in (8, 11):
                continue
            create_run(export, now - timedelta(hours=i), end)

        results = find_missing_intervals([export], *lookback(6))
        assert len(results) == 1
        _, missing = results[0]
        # Hours ending 8 and 11 are not continuous, so they stay as 2 separate intervals
        assert len(missing) == 2
        missing_start, missing_end = missing[0]
        assert missing_start.hour == 7
        assert missing_end.hour == 8
        missing_start, missing_end = missing[1]
        assert missing_start.hour == 10
        assert missing_end.hour == 11

    def test_detects_missing_five_minute_runs(self, team):
        export = create_export(team, interval="every 5 minutes")
        now = timezone.now()

        # Create runs for the last hour, but skip minutes 25 and 40
        for i in range(0, 60, 5):
            if i in (25, 40):
                continue
            create_run(
                export,
                now - timedelta(hours=1) + timedelta(minutes=i),
                now - timedelta(hours=1) + timedelta(minutes=i + 5),
            )

        results = find_missing_intervals([export], *lookback(1))
        assert len(results) == 1
        _, missing = results[0]
        # Minutes 25 and 40 are not continuous, so 2 separate intervals
        assert len(missing) == 2
        missing_start, missing_end = missing[0]
        assert missing_start.minute == 25
        assert missing_end.minute == 30
        missing_start, missing_end = missing[1]
        assert missing_start.minute == 40
        assert missing_end.minute == 45

    def test_detects_missing_daily_runs(self, team):
        export = create_export(team, interval="day")
        now = timezone.now()  # 2026-03-15 12:00:00
        # Daily intervals align to midnight. With 72h lookback from 12:00,
        # expected intervals are: Mar 13 00:00->Mar 14, Mar 14->Mar 15.
        midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        mar13 = midnight_today - timedelta(days=2)
        mar14 = midnight_today - timedelta(days=1)
        mar15 = midnight_today

        # Cover Mar 13->14, leave Mar 14->15 missing
        create_run(export, mar13, mar14)

        results = find_missing_intervals([export], start=mar13, end=mar15)
        assert len(results) == 1
        _, missing = results[0]
        assert len(missing) == 1
        missing_start, missing_end = missing[0]
        assert missing_start == mar14
        assert missing_end == mar15

    @pytest.mark.parametrize(
        "status",
        [
            BatchExportRun.Status.RUNNING,
            BatchExportRun.Status.STARTING,
            BatchExportRun.Status.CONTINUED_AS_NEW,
            BatchExportRun.Status.COMPLETED,
        ],
    )
    def test_covered_statuses_are_not_missing(self, team, status):
        export = create_export(team, interval="hour")
        now = timezone.now()
        create_run(export, now - timedelta(hours=1), now, status=status)

        results = find_missing_intervals([export], *lookback(1))
        # The single interval is covered, so no missing results
        assert results == []

    @pytest.mark.parametrize(
        "status",
        [
            BatchExportRun.Status.FAILED,
            BatchExportRun.Status.CANCELLED,
            BatchExportRun.Status.TIMEDOUT,
        ],
    )
    def test_failed_statuses_are_detected_as_missing(self, team, status):
        export = create_export(team, interval="hour")
        now = timezone.now()
        start = now - timedelta(hours=1)
        end = now
        create_run(export, start, end, status=status)

        results = find_missing_intervals([export], start, end)
        assert len(results) > 0
        _, missing = results[0]
        assert len(missing) == 1
        assert missing[0] == (start, end)

    def test_interval_with_failed_and_completed_run_is_covered(self, team):
        export = create_export(team, interval="hour")
        now = timezone.now()
        start = now - timedelta(hours=1)
        end = now
        create_run(export, start, end, status=BatchExportRun.Status.FAILED)
        create_run(export, start, end, status=BatchExportRun.Status.COMPLETED)

        results = find_missing_intervals([export], start, end)
        assert results == []

    def test_interval_offset_and_timezone_are_respected_for_daily(self, team):
        """Test that the interval offset and timezone are respected when looking for missing intervals."""
        # Offset of 2 hours means daily runs at 02:00 local time.
        # With US/Pacific (UTC-7 in March due to DST), 02:00 PT = 09:00 UTC.
        tz = ZoneInfo("US/Pacific")
        export = create_export(team, interval="day", interval_offset=7200, tz="US/Pacific")

        # Expected intervals in local time (02:00 PT = 09:00 UTC):
        #   Mar 13 09:00 UTC -> Mar 14 09:00 UTC
        #   Mar 14 09:00 UTC -> Mar 15 09:00 UTC
        # Cover Mar 13 -> Mar 14, leave the next one missing
        mar13_2am_local = datetime(2026, 3, 13, 2, 0, tzinfo=tz)
        mar14_2am_local = datetime(2026, 3, 14, 2, 0, tzinfo=tz)
        mar15_2am_local = datetime(2026, 3, 15, 2, 0, tzinfo=tz)
        mar13_2am = mar13_2am_local.astimezone(UTC)
        mar14_2am = mar14_2am_local.astimezone(UTC)
        mar15_2am = mar15_2am_local.astimezone(UTC)
        create_run(export, mar13_2am, mar14_2am)

        # Look for missing intervals between March 13 midnight UTC and March 16 midnight UTC
        # This should detect the missing interval between Mar 14 09:00 UTC and Mar 15 09:00 UTC
        mar13_midnight_utc = datetime(2026, 3, 13, tzinfo=UTC)
        mar16_midnight_utc = datetime(2026, 3, 16, tzinfo=UTC)
        results = find_missing_intervals([export], start=mar13_midnight_utc, end=mar16_midnight_utc)
        assert len(results) == 1
        _, missing = results[0]
        assert missing == [(mar14_2am, mar15_2am)]

    def test_interval_offset_and_timezone_are_respected_for_weekly(self, team):
        """Weekly export on Monday at 02:00 Europe/Berlin should align to local
        timezone boundaries, and detect the two missing weeks between covered runs.

        Note: Europe/Berlin is CET (UTC+1) in Feb/Mar 2026, so 02:00 CET = 01:00 UTC.
        """
        # Weekly on Monday at 02:00 = offset of 1 day + 2 hours = 93600 seconds
        tz = ZoneInfo("Europe/Berlin")
        export = create_export(team, interval="week", interval_offset=93600, tz="Europe/Berlin")

        # Weekly boundaries at Mon 02:00 CET (= 01:00 UTC):
        #   Mon Feb 16 -> Mon Feb 23 (covered)
        #   Mon Feb 23 -> Mon Mar 2  (missing)
        #   Mon Mar 2  -> Mon Mar 9  (missing)
        #   Mon Mar 9  -> Mon Mar 16 (covered)
        feb16 = datetime(2026, 2, 16, 2, 0, tzinfo=tz).astimezone(UTC)  # Mon 01:00 UTC
        feb23 = datetime(2026, 2, 23, 2, 0, tzinfo=tz).astimezone(UTC)  # Mon 01:00 UTC
        mar9 = datetime(2026, 3, 9, 2, 0, tzinfo=tz).astimezone(UTC)  # Mon 01:00 UTC
        mar16 = datetime(2026, 3, 16, 2, 0, tzinfo=tz).astimezone(UTC)  # Mon 01:00 UTC

        create_run(export, feb16, feb23)
        create_run(export, mar9, mar16)

        # choose start and end to cover the whole period, with some buffer
        start = datetime(2026, 2, 15, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 17, 0, 0, tzinfo=UTC)
        results = find_missing_intervals([export], start, end)
        assert len(results) == 1
        _, missing = results[0]
        # The two missing weeks merge into one continuous gap
        assert missing == [(feb23, mar9)]

    def test_daily_intervals_align_correctly_across_dst_spring_forward(self, team):
        """Daily export at 02:00 US/Pacific across the spring-forward DST boundary (Mar 8, 2026).

        Before DST: 02:00 PST = 10:00 UTC
        After DST:  02:00 PDT = 09:00 UTC
        """
        export = create_export(team, interval="day", interval_offset=7200, tz="US/Pacific")

        # Boundaries across the DST transition (note the 23h interval on the DST day):
        #   Mar 7 10:00 UTC (02:00 PST) -> Mar 8 10:00 UTC (02:00 PST)  [covered]
        #   Mar 8 10:00 UTC (02:00 PST) -> Mar 9 09:00 UTC (02:00 PDT)  [missing — 23h]
        #   Mar 9 09:00 UTC (02:00 PDT) -> Mar 10 09:00 UTC (02:00 PDT) [covered]
        mar7 = datetime(2026, 3, 7, 10, 0, tzinfo=UTC)
        mar8 = datetime(2026, 3, 8, 10, 0, tzinfo=UTC)
        mar9 = datetime(2026, 3, 9, 9, 0, tzinfo=UTC)
        mar10 = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)

        # Cover the intervals on either side of the DST gap
        create_run(export, mar7, mar8)
        create_run(export, mar9, mar10)

        results = find_missing_intervals([export], start=mar7, end=mar10)
        assert len(results) == 1
        _, missing = results[0]
        assert missing == [(mar8, mar9)]


def create_noop_export_with_schedule(team, interval="hour"):
    """Create a NoOp batch export with a real Temporal schedule."""
    return create_batch_export(
        team_id=team.pk,
        interval=interval,
        name=f"Test Export {uuid4()}",
        destination_data={"type": "NoOp", "config": {}},
        paused=False,
    )


@async_to_sync
async def delete_temporal_schedule(client, schedule_id: str):
    handle = client.get_schedule_handle(schedule_id)
    await handle.delete()


async def wait_for_workflow(temporal_client: temporalio.client.Client, workflow_id: str, timeout: int = 30) -> None:
    handle = temporal_client.get_workflow_handle(workflow_id)

    for _ in range(timeout):
        try:
            await handle.describe()
            return
        except RPCError as err:
            if err.status != RPCStatusCode.NOT_FOUND:
                raise

        await asyncio.sleep(1)

    raise TimeoutError(f"Timed out waiting for workflow to exist: {workflow_id}")


sync_wait_for_workflow = async_to_sync(wait_for_workflow)


REFERENCE_TIME = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)


def hour_window(hours_back: int) -> tuple[datetime, datetime]:
    """Return a fixed (start, end) window of the given size, relative to REFERENCE_TIME."""
    return REFERENCE_TIME - timedelta(hours=hours_back), REFERENCE_TIME


def run_backfill_command(*args, stderr=None):
    """Run the backfill_batch_export_runs management command with --no-delay and --no-confirm."""
    call_command("backfill_batch_export_runs", *args, "--no-delay", "--no-confirm", stderr=stderr)


def run_backfill_command_with_mocked_temporal(
    *args: str,
    describe_side_effect: Exception | None = None,
    stderr: StringIO | None = None,
) -> tuple[AsyncMock, MagicMock, MagicMock]:
    handle = MagicMock()
    handle.describe = AsyncMock(side_effect=describe_side_effect)
    handle.backfill = AsyncMock()

    client = MagicMock()
    client.get_schedule_handle.return_value = handle

    mock_connect = AsyncMock(return_value=client)
    with patch(f"{COMMAND_MODULE}.connect", new=mock_connect):
        run_backfill_command(*args, stderr=stderr)

    return mock_connect, client, handle


def assert_backfill_requests(
    handle: MagicMock,
    expected_windows: list[tuple[datetime, datetime]],
    overlap_policy: temporalio.client.ScheduleOverlapPolicy = temporalio.client.ScheduleOverlapPolicy.BUFFER_ALL,
) -> None:
    actual_backfills = [await_args.args[0] for await_args in handle.backfill.await_args_list]
    assert [(backfill.start_at, backfill.end_at, backfill.overlap) for backfill in actual_backfills] == [
        (start_at, end_at, overlap_policy) for start_at, end_at in expected_windows
    ]


@pytest.mark.django_db
class TestBackfillCommand:
    """Tests for the batch export backfill management command."""

    @pytest.fixture(scope="class")
    def temporal_client(self):
        return sync_connect()

    @pytest.fixture(scope="class")
    def temporal_test_worker(self, temporal_client):
        """
        Start a Temporal Worker in a separate thread.

        Uses class scoped fixture to save time (stopping the worker takes a while).
        """
        with start_test_worker(
            temporal_client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
        ):
            yield temporal_client

    @pytest.fixture
    def temporal(self, temporal_test_worker, temporal_client):
        yield temporal_client
        for export in BatchExport.objects.all():
            try:
                delete_temporal_schedule(temporal_client, str(export.id))
            except RPCError:
                logging.warning("Schedule %s already deleted", export.id)

    @pytest.mark.parametrize(
        "window_hours, covered_hour_offsets, expected_backfill_offsets",
        [
            pytest.param(2, [(0, 1)], [(2, 2)], id="single_missing_interval"),
            pytest.param(6, [(0, 1), (5, 6)], [(2, 5)], id="merged_missing_intervals"),
            pytest.param(4, [(1, 2), (3, 4)], [(1, 1), (3, 3)], id="non_continuous_gaps"),
            pytest.param(3, [(0, 1), (1, 2), (2, 3)], [], id="fully_covered"),
        ],
    )
    def test_backfill_requests_expected_schedule_windows(
        self,
        team,
        window_hours: int,
        covered_hour_offsets: list[tuple[int, int]],
        expected_backfill_offsets: list[tuple[int, int]],
    ):
        export = create_export(team, interval="hour", destination_type="NoOp")
        start, end = hour_window(window_hours)

        for offset_start, offset_end in covered_hour_offsets:
            create_run(export, start + timedelta(hours=offset_start), start + timedelta(hours=offset_end))

        mock_connect, mock_client, handle = run_backfill_command_with_mocked_temporal(
            f"--batch-export-id={export.id}", f"--start={start.isoformat()}", f"--end={end.isoformat()}"
        )

        expected_windows = [
            (
                start + timedelta(hours=start_offset),
                start + timedelta(hours=end_offset) + export.jitter,
            )
            for start_offset, end_offset in expected_backfill_offsets
        ]
        if expected_windows:
            mock_connect.assert_awaited_once()
            mock_client.get_schedule_handle.assert_called_once_with(str(export.id))
            handle.describe.assert_awaited_once()
            assert_backfill_requests(handle, expected_windows)
        else:
            mock_connect.assert_not_awaited()
            handle.describe.assert_not_awaited()
            handle.backfill.assert_not_awaited()

    def test_single_missing_interval_starts_expected_workflow(self, team, temporal):
        export = create_noop_export_with_schedule(team, interval="hour")
        start, end = hour_window(2)
        create_run(export, start, start + timedelta(hours=1))

        run_backfill_command(
            f"--batch-export-id={export.id}", f"--start={start.isoformat()}", f"--end={end.isoformat()}"
        )

        expected_id = f"{export.id}-{start + timedelta(hours=2):%Y-%m-%dT%H:%M:%SZ}"
        sync_wait_for_workflow(temporal, expected_id)

    def test_daily_backfill_with_offset_and_timezone(self, team):
        # Daily at 02:00 US/Pacific (PDT = UTC-7 during DST), so 02:00 PDT = 09:00 UTC
        export = create_export(team, interval="day", interval_offset=7200, destination_type="NoOp", tz="US/Pacific")

        # 02:00 PDT = 09:00 UTC (well after DST spring-forward on Mar 8)
        day0 = datetime(2026, 3, 29, 9, 0, tzinfo=UTC)  # Sun
        day1 = datetime(2026, 3, 30, 9, 0, tzinfo=UTC)  # Mon
        day2 = datetime(2026, 3, 31, 9, 0, tzinfo=UTC)  # Tue

        # Cover first day, leave second missing
        create_run(export, day0, day1)

        _, mock_client, handle = run_backfill_command_with_mocked_temporal(
            f"--batch-export-id={export.id}",
            f"--start={day0.isoformat()}",
            f"--end={day2.isoformat()}",
        )

        mock_client.get_schedule_handle.assert_called_once_with(str(export.id))
        assert_backfill_requests(handle, [(day2, day2 + export.jitter)])

    def test_weekly_backfill_with_offset_and_timezone(self, team):
        # Weekly on Monday at 02:00 Europe/Berlin
        export = create_export(
            team,
            interval="week",
            interval_offset=93600,
            destination_type="NoOp",
            tz="Europe/Berlin",
        )

        # Crosses DST boundary: Europe/Berlin spring-forward is Mar 29, 2026.
        # Mon 02:00 CET = 01:00 UTC (before DST), Mon 02:00 CEST = 00:00 UTC (after DST)
        week0 = datetime(2026, 3, 16, 1, 0, tzinfo=UTC)  # Mon, CET
        week1 = datetime(2026, 3, 23, 1, 0, tzinfo=UTC)  # Mon, CET
        week2 = datetime(2026, 3, 30, 0, 0, tzinfo=UTC)  # Mon, CEST

        # Cover first week, leave second missing
        create_run(export, week0, week1)

        _, mock_client, handle = run_backfill_command_with_mocked_temporal(
            f"--batch-export-id={export.id}",
            f"--start={week0.isoformat()}",
            f"--end={week2.isoformat()}",
        )

        mock_client.get_schedule_handle.assert_called_once_with(str(export.id))
        assert_backfill_requests(handle, [(week2, week2 + export.jitter)])

    def test_dry_run_does_not_trigger_backfill_requests(self, team):
        export = create_export(team, interval="hour", destination_type="NoOp")
        start, end = hour_window(2)

        mock_connect, mock_client, handle = run_backfill_command_with_mocked_temporal(
            f"--batch-export-id={export.id}", f"--start={start.isoformat()}", f"--end={end.isoformat()}", "--dry-run"
        )

        mock_connect.assert_awaited_once()
        mock_client.get_schedule_handle.assert_called_once_with(str(export.id))
        handle.describe.assert_awaited_once()
        handle.backfill.assert_not_awaited()

    def test_allow_all_overlap_policy(self, team):
        export = create_export(team, interval="hour", destination_type="NoOp")
        start, end = hour_window(2)

        _, mock_client, handle = run_backfill_command_with_mocked_temporal(
            f"--batch-export-id={export.id}",
            f"--start={start.isoformat()}",
            f"--end={end.isoformat()}",
            "--overlap-policy=ALLOW_ALL",
        )

        mock_client.get_schedule_handle.assert_called_once_with(str(export.id))
        assert_backfill_requests(
            handle,
            [(start + timedelta(hours=1), end + export.jitter)],
            temporalio.client.ScheduleOverlapPolicy.ALLOW_ALL,
        )

    def test_schedule_not_found_does_not_raise(self, team):
        export = create_export(team, interval="hour", destination_type="NoOp")
        start, end = hour_window(2)

        stderr = StringIO()
        _, _, handle = run_backfill_command_with_mocked_temporal(
            f"--batch-export-id={export.id}",
            f"--start={start.isoformat()}",
            f"--end={end.isoformat()}",
            describe_side_effect=RPCError("not found", RPCStatusCode.NOT_FOUND, b""),
            stderr=stderr,
        )

        handle.backfill.assert_not_awaited()
        assert f"Schedule {export.id} not found" in stderr.getvalue()
