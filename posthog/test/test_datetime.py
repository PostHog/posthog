from datetime import datetime, timezone

from posthog.datetime import (
    start_of_hour,
    start_of_day,
    end_of_day,
    start_of_week,
    start_of_month,
)


def test_start_of_hour():
    assert start_of_hour(datetime.fromisoformat("2023-02-08T12:05:23+00:00")) == datetime.fromisoformat(
        "2023-02-08T12:00:00+00:00"
    )


def test_start_of_day():
    assert start_of_day(datetime.fromisoformat("2023-02-08T12:05:23+00:00")) == datetime.fromisoformat(
        "2023-02-08T00:00:00+00:00"
    )


def test_end_of_day():
    assert end_of_day(datetime.fromisoformat("2023-02-08T12:05:23+00:00")) == datetime(
        2023, 2, 8, 23, 59, 59, 999999, tzinfo=timezone.utc
    )


def test_start_of_week():
    assert start_of_week(datetime.fromisoformat("2023-02-08T12:05:23+00:00")) == datetime.fromisoformat(
        "2023-02-05T00:00:00+00:00"
    )


def test_start_of_month():
    assert start_of_month(datetime.fromisoformat("2023-02-08T12:05:23+00:00")) == datetime.fromisoformat(
        "2023-02-01T00:00:00+00:00"
    )
