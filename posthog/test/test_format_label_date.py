import datetime
from posthog.utils import format_label_date


def test_format_label_date_with_hour_interval():
    date = datetime.datetime(2022, 12, 31, 23, 59)
    interval = "hour"
    formatted_date = format_label_date(date, interval)
    assert formatted_date == "31-Dec-2022 23:59"


def test_format_label_date_with_month_interval():
    date = datetime.datetime(2022, 12, 31)
    interval = "month"
    formatted_date = format_label_date(date, interval)
    assert formatted_date == "Dec 2022"


def test_format_label_date_with_default_interval():
    date = datetime.datetime(2022, 12, 31)
    interval = "year"
    formatted_date = format_label_date(date, interval)
    assert formatted_date == "31-Dec-2022"


def test_format_label_date_with_missing_interval():
    date = datetime.datetime(2022, 12, 31)
    formatted_date = format_label_date(date)
    assert formatted_date == "31-Dec-2022"


def test_format_label_date_with_empty_string_interval():
    date = datetime.datetime(2022, 12, 31)
    interval = ""
    formatted_date = format_label_date(date, interval)
    assert formatted_date == "31-Dec-2022"
