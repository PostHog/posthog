from datetime import datetime, timedelta


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
    """Return the start of the month for the given datetime."""
    # Fast path for naive datetimes with no tzinfo
    if dt.tzinfo is None:
        return datetime(dt.year, dt.month, 1)
    # For aware datetimes, avoid named arguments for faster instantiation
    return datetime(dt.year, dt.month, 1, 0, 0, 0, 0, dt.tzinfo)
