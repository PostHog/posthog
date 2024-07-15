import datetime
from typing import Optional, Any

import pytz


def is_hog_date(obj: Any) -> bool:
    return isinstance(obj, dict) and "__hogDate__" in obj and "year" in obj and "month" in obj and "day" in obj


def is_hog_datetime(obj: Any) -> bool:
    return isinstance(obj, dict) and "__hogDateTime__" in obj and "dt" in obj and "zone" in obj


def to_hog_date(year: int, month: int, day: int):
    return {
        "__hogDate__": True,
        "year": year,
        "month": month,
        "day": day,
    }


def to_hog_datetime(timestamp: float | dict, zone: Optional[str] = None):
    if isinstance(timestamp, dict) and is_hog_date(timestamp):
        dt = datetime.datetime(
            year=timestamp["year"], month=timestamp["month"], day=timestamp["day"], tzinfo=pytz.timezone(zone or "UTC")
        )
        return {
            "__hogDateTime__": True,
            "dt": dt.timestamp(),
            "zone": (dt.tzinfo.tzname(None) if dt.tzinfo else None) or "UTC",
        }
    return {
        "__hogDateTime__": True,
        "dt": timestamp,
        "zone": zone or "UTC",
    }


# Exported functions


def now(zone: Optional[str] = None):
    return to_hog_datetime(datetime.datetime.now().timestamp(), zone)


def toUnixTimestamp(date, timezone: Optional[str] = None):
    if isinstance(date, dict) and is_hog_datetime(date):
        return date["dt"]
    if isinstance(date, dict) and is_hog_date(date):
        return datetime.datetime(
            year=date["year"], month=date["month"], day=date["day"], tzinfo=pytz.timezone(timezone or "UTC")
        ).timestamp()

    date = datetime.datetime.fromisoformat(date)
    if timezone:
        date = date.astimezone(pytz.timezone(timezone))
    return date.timestamp()


def fromUnixTimestamp(timestamp: float):
    return to_hog_datetime(timestamp)


def toTimeZone(date: dict, timezone: str):
    if not is_hog_datetime(date):
        raise ValueError("Expected a DateTime")
    return {
        **date,
        "zone": timezone,
    }


def toDate(string):
    dt = datetime.datetime.fromisoformat(string)
    return {
        "__hogDate__": True,
        "year": dt.year,
        "month": dt.month,
        "day": dt.day,
    }


def toDateTime(string):
    dt = datetime.datetime.fromisoformat(string)
    return {
        "__hogDateTime__": True,
        "dt": dt.timestamp(),
        "zone": "UTC",
    }
