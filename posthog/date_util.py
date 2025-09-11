from datetime import UTC, datetime, timedelta


def start_of_minute(dt: datetime) -> datetime:
    return datetime(year=dt.year, month=dt.month, day=dt.day, hour=dt.hour, minute=dt.minute, tzinfo=dt.tzinfo)


def start_of_hour(dt: datetime) -> datetime:
    return datetime(year=dt.year, month=dt.month, day=dt.day, hour=dt.hour, tzinfo=dt.tzinfo)


def start_of_day(dt: datetime):
    return datetime(year=dt.year, month=dt.month, day=dt.day, tzinfo=dt.tzinfo)


def end_of_day(dt: datetime):
    return datetime(year=dt.year, month=dt.month, day=dt.day, tzinfo=dt.tzinfo) + timedelta(days=1, microseconds=-1)


def start_of_week(dt: datetime) -> datetime:
    # weeks start on sunday
    return datetime(year=dt.year, month=dt.month, day=dt.day, tzinfo=dt.tzinfo) - timedelta(days=(dt.weekday() + 1) % 7)


def start_of_month(dt: datetime) -> datetime:
    return datetime(year=dt.year, month=dt.month, day=1, tzinfo=dt.tzinfo)


def thirty_days_ago() -> datetime:
    return datetime.now(UTC) - timedelta(days=30)
