import datetime as dt

from unittest import TestCase

from products.alerts.backend.evaluation.absence import absent_trailing_buckets


def _at(hour: int, minute: int = 0, offset_hours: int = 0) -> str:
    tz = dt.timezone(dt.timedelta(hours=offset_hours))
    return dt.datetime(2026, 7, 1, hour, minute, tzinfo=tz).isoformat()


def _now(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 7, 1, hour, minute, tzinfo=dt.UTC)


class TestAbsentTrailingBuckets(TestCase):
    def test_reporting_metric_pads_nothing(self) -> None:
        # 08:00 is still accumulating; 07:00 is the last complete bucket and it has data.
        self.assertEqual(absent_trailing_buckets([_at(6), _at(7), _at(8)], _now(8, 55)), [])

    def test_stopped_metric_pads_the_complete_buckets_it_missed(self) -> None:
        # Last sample landed in the 06:00 bucket. 07:00 closed at 08:00 and never reported;
        # 08:00 does not close until 09:00, so it is not yet missing.
        self.assertEqual(absent_trailing_buckets([_at(4), _at(5), _at(6)], _now(8, 55)), [_at(7)])

    def test_ongoing_bucket_is_never_padded(self) -> None:
        # 07:00 closes exactly at 08:00. One second earlier it is still accumulating.
        self.assertEqual(absent_trailing_buckets([_at(5), _at(6)], _now(7, 59)), [])
        self.assertEqual(absent_trailing_buckets([_at(5), _at(6)], _now(8, 0)), [_at(7)])

    def test_single_bucket_gives_no_cadence_to_infer_from(self) -> None:
        # One observed bucket cannot tell us how often this metric reports, so padding
        # would be guesswork. Fail closed: never invent a breach we cannot justify.
        self.assertEqual(absent_trailing_buckets([_at(6)], _now(20)), [])
        self.assertEqual(absent_trailing_buckets([], _now(20)), [])

    def test_cadence_self_calibrates_to_a_sparse_metric(self) -> None:
        # Reports every 3h. At 08:55 the 09:00 bucket has not even opened, so nothing is late.
        every_three_hours = [_at(0), _at(3), _at(6)]
        self.assertEqual(absent_trailing_buckets(every_three_hours, _now(8, 55)), [])
        # By 12:30 the 09:00 bucket has closed unreported.
        self.assertEqual(absent_trailing_buckets(every_three_hours, _now(12, 30)), [_at(9)])

    def test_interior_gap_does_not_inflate_the_inferred_cadence(self) -> None:
        # 08:00 is missing mid-series. The cadence is still hourly (the smallest gap),
        # not two-hourly — a mean or max would read this as a slower metric and under-report.
        self.assertEqual(absent_trailing_buckets([_at(6), _at(7), _at(9)], _now(11, 30)), [_at(10)])

    def test_long_dead_metric_is_capped(self) -> None:
        padded = absent_trailing_buckets([_at(0), _at(1)], _now(23, 59), max_buckets=3)
        self.assertEqual(padded, [_at(2), _at(3), _at(4)])

    def test_naive_bucket_times_are_read_as_utc(self) -> None:
        naive = [dt.datetime(2026, 7, 1, 5).isoformat(), dt.datetime(2026, 7, 1, 6).isoformat()]
        self.assertEqual(absent_trailing_buckets(naive, _now(8, 0)), [_at(7)])

    def test_project_timezone_offset_is_preserved(self) -> None:
        # HogQL renders bucket times in the project timezone, so the padded buckets must
        # keep that offset — they are compared against UTC now, and displayed to the user.
        berlin = [_at(7, offset_hours=2), _at(8, offset_hours=2)]
        self.assertEqual(absent_trailing_buckets(berlin, _now(8, 0)), [_at(9, offset_hours=2)])
