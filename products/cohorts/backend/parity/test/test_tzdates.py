from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.parity.tzdates import day_of_instant, start_of_day_utc, window_dates, window_start_utc

PACIFIC = ZoneInfo("US/Pacific")


class TestTzDates(SimpleTestCase):
    @parameterized.expand(
        [
            # An evening UTC instant is still the previous calendar day in US/Pacific.
            ("evening_utc_is_previous_pacific_day", datetime(2026, 7, 24, 2, 0, tzinfo=UTC), date(2026, 7, 23)),
            ("midday_utc_same_pacific_day", datetime(2026, 7, 24, 18, 0, tzinfo=UTC), date(2026, 7, 24)),
        ]
    )
    def test_day_of_instant(self, _name: str, instant: datetime, expected: date) -> None:
        self.assertEqual(day_of_instant(instant, PACIFIC), expected)

    def test_day_of_instant_rejects_naive(self) -> None:
        with self.assertRaises(ValueError):
            day_of_instant(datetime(2026, 7, 24, 2, 0), PACIFIC)

    @parameterized.expand(
        [
            # Standard time (PST, -8): midnight is 08:00 UTC.
            ("pst_midnight", date(2026, 1, 15), datetime(2026, 1, 15, 8, 0, tzinfo=UTC)),
            # Daylight time (PDT, -7): midnight is 07:00 UTC.
            ("pdt_midnight", date(2026, 7, 15), datetime(2026, 7, 15, 7, 0, tzinfo=UTC)),
            # Spring-forward day (transition at 02:00): midnight predates the gap, still PST.
            ("spring_forward_midnight_pst", date(2026, 3, 8), datetime(2026, 3, 8, 8, 0, tzinfo=UTC)),
            # Fall-back day (transition at 02:00): midnight predates the overlap, still PDT.
            ("fall_back_midnight_pdt", date(2026, 11, 1), datetime(2026, 11, 1, 7, 0, tzinfo=UTC)),
        ]
    )
    def test_start_of_day_utc_pacific(self, _name: str, day: date, expected: datetime) -> None:
        self.assertEqual(start_of_day_utc(day, PACIFIC), expected)

    def test_start_of_day_utc_spring_forward_gap_midnight_lands_post_gap(self) -> None:
        # Sao Paulo sprang forward at midnight 2017-10-15 (00:00 -> 01:00), so local midnight does
        # not exist. Rust's bucket_tz resolves it to the post-gap instant (01:00 local); fold=0 must
        # match exactly rather than fall on the pre-gap side.
        sao_paulo = ZoneInfo("America/Sao_Paulo")
        start = start_of_day_utc(date(2017, 10, 15), sao_paulo)
        self.assertEqual(start, datetime(2017, 10, 15, 3, 0, tzinfo=UTC))
        self.assertEqual(start.astimezone(sao_paulo).hour, 1)

    def test_start_of_day_utc_skipped_civil_day_projects_to_following_midnight(self) -> None:
        # Apia skipped all of 2011-12-30; its midnight and the following day's midnight are the same
        # instant, matching bucket_tz's fully-skipped-civil-day golden.
        apia = ZoneInfo("Pacific/Apia")
        self.assertEqual(start_of_day_utc(date(2011, 12, 30), apia), datetime(2011, 12, 30, 10, 0, tzinfo=UTC))
        self.assertEqual(start_of_day_utc(date(2011, 12, 31), apia), datetime(2011, 12, 30, 10, 0, tzinfo=UTC))

    def test_start_of_day_utc_fall_back_ambiguous_midnight_is_earliest(self) -> None:
        # Lord Howe falls back through 02:00->01:30, but some zones overlap midnight. Use a zone that
        # falls back at 00:00 to exercise the ambiguous branch: America/Havana fell back 2018-11-04
        # (01:00 -> 00:00), so 00:00 occurs twice; fold=0 must pick the earliest (pre-transition) UTC.
        havana = ZoneInfo("America/Havana")
        start = start_of_day_utc(date(2018, 11, 4), havana)
        # 00:00 CDT (-4) is the earliest instant = 04:00 UTC (vs the later 00:00 CST (-5) = 05:00 UTC).
        self.assertEqual(start, datetime(2018, 11, 4, 4, 0, tzinfo=UTC))

    @parameterized.expand(
        [
            # N-day window over inclusive [at_day - N .. at_day] = N + 1 dates. This is the off-by-one
            # the plan flags as the highest-risk regression: a window of N must yield N + 1 buckets.
            ("zero_day_window_is_one_bucket", 0, [date(2026, 7, 24)]),
            (
                "seven_day_window_is_eight_buckets",
                7,
                [
                    date(2026, 7, 17),
                    date(2026, 7, 18),
                    date(2026, 7, 19),
                    date(2026, 7, 20),
                    date(2026, 7, 21),
                    date(2026, 7, 22),
                    date(2026, 7, 23),
                    date(2026, 7, 24),
                ],
            ),
        ]
    )
    def test_window_dates_inclusive_n_plus_one(self, _name: str, window_days: int, expected: list[date]) -> None:
        # 18:00 UTC on 2026-07-24 is still 2026-07-24 in US/Pacific (11:00 PDT).
        at = datetime(2026, 7, 24, 18, 0, tzinfo=UTC)
        dates = window_dates(at, window_days, PACIFIC)
        self.assertEqual(dates, expected)
        self.assertEqual(len(dates), window_days + 1)

    def test_window_start_utc_is_midnight_of_at_day_minus_n(self) -> None:
        at = datetime(2026, 7, 24, 18, 0, tzinfo=UTC)  # 2026-07-24 in US/Pacific
        # at_day - 7 = 2026-07-17; PDT midnight = 07:00 UTC.
        self.assertEqual(window_start_utc(at, 7, PACIFIC), datetime(2026, 7, 17, 7, 0, tzinfo=UTC))
        # The start must equal start_of_day_utc of the first window date.
        first_window_day = window_dates(at, 7, PACIFIC)[0]
        self.assertEqual(window_start_utc(at, 7, PACIFIC), start_of_day_utc(first_window_day, PACIFIC))
