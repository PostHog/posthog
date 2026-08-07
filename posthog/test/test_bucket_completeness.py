from datetime import datetime, timedelta

import pytest

from dateutil.relativedelta import relativedelta

from posthog.bucket_completeness import bucket_starts, incomplete_from_index, parse_bucket_start, partial_bucket_flags

DAILY = ["2026-08-04", "2026-08-05", "2026-08-06"]
DAY = timedelta(days=1)


class TestParseBucketStart:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("2026-08-06", datetime(2026, 8, 6)),
            ("2026-08-06 13:00:00", datetime(2026, 8, 6, 13)),
            ("2026-08-06T13:00:00Z", datetime(2026, 8, 6, 13)),
        ],
    )
    def test_known_shapes_parse_to_naive_local(self, label, expected):
        assert parse_bucket_start(label) == expected

    # Stickiness puts integer day-counts in `days`, so coercion here would invent a date axis.
    @pytest.mark.parametrize("label", [3, None, {"a": 1}, "not a date", ""])
    def test_anything_else_is_rejected(self, label):
        assert parse_bucket_start(label) is None


class TestBucketStarts:
    def test_a_usable_list_parses(self):
        assert bucket_starts(DAILY) == [datetime(2026, 8, 4), datetime(2026, 8, 5), datetime(2026, 8, 6)]

    # A partly parseable list would leave neighbours that are not really adjacent.
    @pytest.mark.parametrize("days", [["2026-08-04", "nope"], [1, 2, 3], [], None, "2026-08-04"])
    def test_anything_less_than_all_is_nothing(self, days):
        assert bucket_starts(days) is None


class TestIncompleteFromIndex:
    @pytest.mark.parametrize(
        "reference,expected",
        [
            (datetime(2026, 8, 6, 12), 2),  # midway through the final bucket
            (datetime(2026, 8, 6, 0), 2),  # the instant it opens
            (datetime(2026, 8, 7, 0), None),  # the instant it closes, so complete
            (datetime(2026, 8, 5, 12), 1),  # two buckets unfinished
        ],
    )
    def test_finds_the_first_unfinished_bucket(self, reference, expected):
        assert incomplete_from_index(bucket_starts(DAILY), reference=reference, period=DAY) == expected

    # Extrapolating a calendar bucket's end from the previous gap both kept partial periods and
    # dropped complete ones, depending on which way the month lengths fell.
    @pytest.mark.parametrize(
        "days,reference,period,expected",
        [
            (["2026-01-01", "2026-02-01"], datetime(2026, 3, 3), relativedelta(months=1), None),
            (["2026-01-01", "2026-02-01", "2026-03-01"], datetime(2026, 3, 30), relativedelta(months=1), 2),
            (["2026-01-01", "2026-02-01", "2026-03-01"], datetime(2026, 4, 1), relativedelta(months=1), None),
            (["2025-07-01", "2025-10-01", "2026-01-01"], datetime(2026, 2, 15), relativedelta(months=3), 2),
            (["2024-01-01", "2025-01-01", "2026-01-01"], datetime(2026, 6, 1), relativedelta(years=1), 2),
        ],
    )
    def test_calendar_periods_step_by_themselves(self, days, reference, period, expected):
        assert incomplete_from_index(bucket_starts(days), reference=reference, period=period) == expected

    @pytest.mark.parametrize(
        "starts,reference,period,reason",
        [
            (None, datetime(2026, 8, 6, 12), DAY, "no buckets"),
            ([], datetime(2026, 8, 6, 12), DAY, "empty buckets"),
            (bucket_starts(DAILY), None, DAY, "no reference"),
            (bucket_starts(DAILY), datetime(2026, 8, 6, 12), None, "no period"),
            # Timestamps disagreeing with each other is not the same as the data being missing, and
            # trimming everything would leave nothing to describe.
            (bucket_starts(DAILY), datetime(2020, 1, 1), DAY, "every bucket looks unfinished"),
        ],
    )
    def test_undecidable_cases_report_nothing(self, starts, reference, period, reason):
        assert incomplete_from_index(starts, reference=reference, period=period) is None, reason


class TestPartialBucketFlags:
    def test_flags_the_current_interval_and_later(self):
        assert partial_bucket_flags(DAILY, datetime(2026, 8, 5)) == [False, True, True]

    def test_unparseable_labels_are_not_flagged(self):
        assert partial_bucket_flags(["nope", "2026-08-06"], datetime(2026, 8, 5)) == [False, True]
