import datetime
from typing import Optional

import pytz

from common.hogvm.python.objects import is_hog_date, is_hog_datetime


def to_hog_date(year: int, month: int, day: int):
    return {
        "__hogDate__": True,
        "year": year,
        "month": month,
        "day": day,
    }


def to_hog_datetime(timestamp: int | float | dict, zone: Optional[str] = None):
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


def fromUnixTimestamp(timestamp: int | float):
    return to_hog_datetime(timestamp)


def toUnixTimestampMilli(date, timezone: Optional[str] = None):
    return int(toUnixTimestamp(date, timezone) * 1000)


def fromUnixTimestampMilli(timestamp: int):
    return fromUnixTimestamp(float(timestamp) / 1000.0)


def toTimeZone(date: dict, timezone: str):
    if not is_hog_datetime(date):
        raise ValueError("Expected a DateTime")
    return {
        **date,
        "zone": timezone,
    }


def toDate(input):
    if isinstance(input, int) or isinstance(input, float):
        dt = datetime.datetime.fromtimestamp(input)
    else:
        dt = datetime.datetime.fromisoformat(input)
    return {
        "__hogDate__": True,
        "year": dt.year,
        "month": dt.month,
        "day": dt.day,
    }


def toDateTime(input):
    if isinstance(input, int) or isinstance(input, float):
        dt = float(input)
    else:
        dt = datetime.datetime.fromisoformat(input).timestamp()
    return {
        "__hogDateTime__": True,
        "dt": dt,
        "zone": "UTC",
    }


# From ClickHouse to Python
token_translations = {
    "a": "%a",
    "b": "%b",
    "c": "%m",
    "C": "%y",
    "d": "%d",
    "D": "%m/%d/%y",
    "e": "%d",
    "f": "%f",
    "F": "%Y-%m-%d",
    "g": "%y",
    "G": "%Y",
    "h": "%I",
    "H": "%H",
    "i": "%M",
    "I": "%I",
    "j": "%j",
    "k": "%H",
    "l": "%I",
    "m": "%m",
    "M": "%B",
    "n": "\n",
    "p": "%p",
    # 'Q': '%Q',
    "r": "%I:%M %p",
    "R": "%H:%M",
    "s": "%S",
    "S": "%S",
    "t": "\t",
    "T": "%H:%M:%S",
    "u": "%u",
    "V": "%V",
    "w": "%w",
    "W": "%A",
    "y": "%y",
    "Y": "%Y",
    "z": "%z",
    "%": "%%",
}


def formatDateTime(input: dict, format: str, zone: Optional[str] = None) -> str:
    if not is_hog_datetime(input):
        raise ValueError("Expected a DateTime")
    format_string = ""
    acc = ""
    i = 0
    while i < len(format):
        if format[i] == "%":
            if acc:
                format_string += acc
                acc = ""
            i += 1
            if i < len(format) and format[i] in token_translations:
                format_string += token_translations[format[i]]
        else:
            acc += format[i]
        i += 1
    if acc:
        format_string += acc
    return datetime.datetime.fromtimestamp(input["dt"], pytz.timezone(zone or input["zone"])).strftime(format_string)
