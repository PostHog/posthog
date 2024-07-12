import datetime
from typing import Optional

import pytz


def now():
    return datetime.datetime.now()


def toUnixTimestamp(date, timezone: Optional[str] = None):
    if isinstance(date, datetime.date) and not isinstance(date, datetime.datetime):
        date = datetime.datetime(date.year, date.month, date.day, tzinfo=pytz.timezone(timezone or "UTC"))
    if isinstance(date, str):
        date = datetime.datetime.fromisoformat(date)
        if timezone:
            date = date.astimezone(pytz.timezone(timezone))
    return date.timestamp()


def fromUnixTimestamp(timestamp):
    return datetime.datetime.fromtimestamp(timestamp, tz=datetime.UTC)


def toTimeZone(date, timezone: str):
    return date.astimezone(pytz.timezone(timezone))


def toDate(string):
    return datetime.date.fromisoformat(string)


def toDateTime(string):
    return datetime.datetime.fromisoformat(string)
