from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest

from dateutil import parser

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange


class TestQueryPreviousPeriodDateRange(APIBaseTest):
    def test_previous_period(self):
        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        query_date_range = QueryPreviousPeriodDateRange(
            team=self.team, date_range=date_range, interval=IntervalType.DAY, now=now
        )
        # 2 days ago from now = 2021-08-23T00:00 → previous period of equal length
        # goes back another 2 days (-48h shifted back by 48h).
        self.assertEqual(query_date_range.date_from(), parser.isoparse("2021-08-21T00:00:00Z"))
        self.assertEqual(query_date_range.date_to(), parser.isoparse("2021-08-22T23:59:59.999999Z"))

    def test_explicit_timezone_info_overrides_team_timezone(self):
        # The previous-period delta parsing used to read directly from
        # `self._team.timezone_info`, so a `timezone_info=UTC` override on the constructor
        # was silently ignored. With the fix it should resolve the date range in the
        # explicitly-passed timezone.
        self.team.timezone = "US/Pacific"
        self.team.save()

        now = parser.isoparse("2021-08-25T00:00:00.000Z")
        date_range = DateRange(date_from="-48h")
        with_override = QueryPreviousPeriodDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
            timezone_info=ZoneInfo("UTC"),
        )

        # Same setup with team on UTC and no override — should match the override result.
        self.team.timezone = "UTC"
        self.team.save()
        utc_baseline = QueryPreviousPeriodDateRange(
            team=self.team,
            date_range=date_range,
            interval=IntervalType.DAY,
            now=now,
        )
        self.assertEqual(with_override.date_from(), utc_baseline.date_from())
        self.assertEqual(with_override.date_to(), utc_baseline.date_to())
