"""Test utilities that operate with datetime.datetimes."""

import datetime as dt


def date_range(start: dt.datetime, stop: dt.datetime, step: dt.timedelta):
    """Generate a range of dates between two dates."""
    current = start

    while current < stop:
        yield current
        current += step


def to_isoformat(d: str | None) -> str | None:
    """Parse a string and return it as default isoformatted."""
    if d is None:
        return None
    return dt.datetime.fromisoformat(d).replace(tzinfo=dt.UTC).isoformat()
