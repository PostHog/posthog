import re
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

    # A naive string is anchored to `timezone` (UTC when unset), matching Rust's
    # `naive_to_seconds(s, zone)` and TypeScript's `fromISO(input, {zone})`. It used to be parsed
    # naive and then `.astimezone`d, which is a no-op for aware input and resolves naive input in the
    # *host's* timezone — so the answer depended on where the process happened to be running.
    parsed = _parse_date_like(date, timezone)
    if parsed is None:
        raise ValueError(f"Could not parse date: {date}")
    return parsed.timestamp()


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


# [0-9] and never \d: Python's re treats \d as any Unicode decimal digit, which int() then happily
# parses — so e.g. an all-Arabic-Indic-digit date was a valid instant here and rejected by the
# other two VMs. See the canonical grammar in the Rust STL.
DATE_LIKE = re.compile(
    r"""^([0-9]{4})-([0-9]{2})-([0-9]{2})
        (?:
            [Tt\ ]([01][0-9]|2[0-3]):([0-5][0-9])
            (?::([0-5][0-9])(?:[.,]([0-9]{1,9}))?)?
            (Z|z|[+-](?:[01][0-9]|2[0-3])(?::?[0-5][0-9])?)?
        )?\Z""",
    re.VERBOSE,
)


def _parse_date_like(input: str, timezone: Optional[str] = None) -> Optional[datetime.datetime]:
    """An aware ``datetime`` for a string matching the shared date-like grammar, else None.

    The canonical copy of the grammar lives above ``parse_datetime_to_seconds`` in
    ``rust/common/hogvm/src/stl.rs``; ``common/hogvm/typescript/src/stl/date.ts`` (``parseDateLike``)
    is the third implementation. Change all three together.

    Deliberately not ``datetime.fromisoformat``, which accepts the compact ``20240101`` and ISO-week
    ``2024-W05`` forms that neither of the other two VMs do. More importantly, ``fromisoformat``
    returns a *naive* datetime for input carrying no zone, and ``naive.timestamp()`` resolves it in
    the **host's** timezone — so the Python VM's answer for ``toDateTime('2026-07-01')`` depended on
    where it happened to be running, and disagreed with TypeScript and Rust (both UTC-anchored) by
    the local UTC offset. ``tzinfo`` is always set here, so the result is host-independent.

    ``timezone`` applies only to input carrying no zone of its own; an explicit offset or ``Z`` pins
    the absolute instant regardless.
    """
    match = DATE_LIKE.match(input.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, fraction, offset = match.groups()
    # Sub-millisecond digits are truncated, not rounded, to match luxon and Rust's `timestamp_millis`.
    # Python's `datetime` keeps microseconds, which surfaced as a `result_mismatch` against the Node
    # baseline (see `datetime_to_seconds` in the Rust STL).
    microsecond = int(fraction[:3].ljust(3, "0")) * 1000 if fraction else 0

    try:
        if offset in ("Z", "z"):
            tzinfo: datetime.tzinfo = datetime.UTC
        elif offset:
            digits = offset[1:].replace(":", "")
            delta = datetime.timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
            tzinfo = datetime.timezone(-delta if offset[0] == "-" else delta)
        else:
            tzinfo = pytz.timezone(timezone or "UTC")

        naive = datetime.datetime(
            int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0), microsecond
        )
    except ValueError:
        # Out-of-range calendar date (2024-02-30) or year 0. The tz construction is inside the `try`
        # deliberately: an offset the regex admits but `datetime.timezone` rejects must return None
        # like any other parse failure — this function is called from `unify_comparison_types` on
        # every comparison opcode, where a bare ValueError would escape the VM entirely rather than
        # leaving the operands uncoerced. (An unknown zone *name* still raises — pytz's
        # UnknownTimeZoneError is a KeyError — matching the natives' pre-existing behavior; only
        # they pass a zone, never the comparison path.)
        return None
    # `localize` rather than `tzinfo=` — pytz zones carry a historical LMT offset that only
    # `localize` resolves to the right one for the date in question. `is_dst=True` picks the first
    # of an ambiguous pair during a DST fold, matching Rust's `LocalResult::Ambiguous(dt, _)` and
    # luxon; pytz's default (`is_dst=False`) would pick the second and land an hour off.
    localize = getattr(tzinfo, "localize", None)
    return localize(naive, is_dst=True) if localize else naive.replace(tzinfo=tzinfo)


def toDate(input):
    if isinstance(input, int) or isinstance(input, float):
        dt = datetime.datetime.fromtimestamp(input)
    else:
        parsed = _parse_date_like(input)
        if parsed is None:
            raise ValueError(f"Could not parse date: {input}")
        dt = parsed
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
        parsed = _parse_date_like(input)
        if parsed is None:
            raise ValueError(f"Could not parse date: {input}")
        dt = parsed.timestamp()
    return {
        "__hogDateTime__": True,
        "dt": dt,
        "zone": "UTC",
    }


def date_string_to_seconds(input: str) -> Optional[float]:
    """Epoch seconds for a date-like string, parsed the same way `toDateTime` would, else None."""
    parsed = _parse_date_like(input)
    return parsed.timestamp() if parsed else None


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
