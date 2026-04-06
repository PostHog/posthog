import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from unittest.mock import AsyncMock, MagicMock

from django.utils import timezone

from posthog.batch_exports.models import BatchExport, BatchExportDestination, BatchExportRun
from posthog.management.commands.backfill_batch_export_runs import (
    backfill_export,
    find_missing_intervals,
    get_backfill_bounds,
    get_batch_exports,
)
from posthog.models import Organization, Team


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org")


@pytest.fixture
def team(org):
    return Team.objects.create(organization=org, name="Test Team")


def create_export(team, interval="hour", interval_offset=None, paused=False, destination_type="S3", tz="UTC"):
    destination = BatchExportDestination.objects.create(type=destination_type, config={})
    return BatchExport.objects.create(
        team=team,
        name=f"Test Export {uuid4()}",
        destination=destination,
        interval=interval,
        interval_offset=interval_offset,
        paused=paused,
        timezone=tz,
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


class TestGetBackfillBounds:
    @pytest.mark.parametrize(
        "interval,expected_padding",
        [
            ("hour", timedelta(minutes=30)),
            ("day", timedelta(hours=2)),
            ("week", timedelta(hours=6)),
            ("every 5 minutes", timedelta(minutes=2)),
            ("every 15 minutes", timedelta(minutes=2)),
        ],
    )
    def test_single_interval_returns_correct_window(self, interval, expected_padding):
        first_end = timezone.now()
        start_at, end_at = get_backfill_bounds(interval, first_end, first_end)
        assert start_at == first_end
        assert end_at == first_end + expected_padding

    def test_range_spans_first_to_last_plus_padding(self):
        first_end = timezone.now()
        last_end = first_end + timedelta(hours=3)
        start_at, end_at = get_backfill_bounds("hour", first_end, last_end)
        assert start_at == first_end
        assert end_at == last_end + timedelta(minutes=30)

    def test_unsupported_interval_raises(self):
        now = timezone.now()
        with pytest.raises(ValueError):
            get_backfill_bounds("month", now, now)


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

        start = datetime(2026, 2, 16, 1, 0, tzinfo=UTC)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        results = find_missing_intervals([export], start, end)
        assert len(results) == 1
        _, missing = results[0]
        # The two missing weeks merge into one continuous gap
        assert missing == [(feb23, mar9)]

    def test_daily_intervals_align_correctly_across_dst_spring_forward(self, team):
        """Daily export at 02:00 US/Pacific across the spring-forward DST boundary (Mar 8, 2026).

        Before DST: 02:00 PST = 10:00 UTC
        After DST:  02:00 PDT = 09:00 UTC

        The spring-forward day (Mar 8) has 02:00 PST = 10:00 UTC (pre-transition
        offset for the non-existent local time). The next day shifts to 09:00 UTC.
        The script must detect gaps at these correct local-time boundaries.
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


@pytest.mark.django_db
class TestBackfillExport:
    @pytest.fixture
    def batch_export(self, team):
        return create_export(team, interval="hour")

    @pytest.fixture
    def temporal_mocks(self):
        handle = AsyncMock()
        handle.describe = AsyncMock()
        handle.backfill = AsyncMock()
        client = MagicMock()
        client.get_schedule_handle.return_value = handle
        return client, handle

    @staticmethod
    def _make_missing_intervals(count=2):
        now = timezone.now()
        return [(now - timedelta(hours=i + 1), now - timedelta(hours=i)) for i in range(count, 0, -1)]

    def test_dry_run_does_not_call_backfill(self, batch_export, temporal_mocks):
        client, handle = temporal_mocks
        intervals = self._make_missing_intervals(2)
        count = asyncio.run(backfill_export(client, batch_export, intervals, dry_run=True))
        assert count == 2
        handle.backfill.assert_not_called()

    def test_backfill_calls_temporal(self, batch_export, temporal_mocks):
        client, handle = temporal_mocks
        intervals = self._make_missing_intervals(2)
        count = asyncio.run(backfill_export(client, batch_export, intervals, dry_run=False))
        assert count == 2
        assert handle.backfill.call_count == 2

    def test_schedule_not_found_returns_zero(self, batch_export, temporal_mocks):
        client, handle = temporal_mocks
        handle.describe = AsyncMock(side_effect=Exception("Schedule not found"))
        intervals = self._make_missing_intervals(2)
        count = asyncio.run(backfill_export(client, batch_export, intervals, dry_run=False))
        assert count == 0
        handle.backfill.assert_not_called()
