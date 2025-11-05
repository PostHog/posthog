import re
import json
import math
import time
import datetime
import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

import pytz

from ..objects import is_hog_callable, is_hog_closure, is_hog_error, new_hog_error, to_hog_interval
from ..utils import get_nested_value, like
from .cohort import inCohort, notInCohort
from .crypto import md5, sha256, sha256HmacChain
from .date import (
    formatDateTime,
    fromUnixTimestamp,
    fromUnixTimestampMilli,
    is_hog_date,
    is_hog_datetime,
    now,
    toDate,
    toDateTime,
    toTimeZone,
    toUnixTimestamp,
    toUnixTimestampMilli,
)
from .ip import isIPAddressInRange
from .print import print_hog_string_output

if TYPE_CHECKING:
    from posthog.models import Team


@dataclasses.dataclass
class STLFunction:
    fn: Callable[[list[Any], Optional["Team"], list[str] | None, float], Any]
    minArgs: Optional[int] = None
    maxArgs: Optional[int] = None


def toString(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float):
    if isinstance(args[0], dict) and is_hog_datetime(args[0]):
        dt = datetime.datetime.fromtimestamp(args[0]["dt"], pytz.timezone(args[0]["zone"] or "UTC"))
        if args[0]["zone"] == "UTC":
            return dt.isoformat("T", "milliseconds").replace("+00:00", "") + "Z"
        return dt.isoformat("T", "milliseconds")
    elif isinstance(args[0], dict) and is_hog_date(args[0]):
        year = args[0]["year"]
        month = args[0]["month"]
        day = args[0]["day"]
        return f"{year}-{month:02d}-{day:02d}"
    elif isinstance(args[0], dict) and is_hog_error(args[0]):
        return (
            f"{args[0]['name']}({toString(args[0]['message'], team, stdout, timeout)}"
            + (f", {toString(args[0]['payload'], team, stdout, timeout)}" if "payload" in args[0] else "")
            + ")"
        )
    elif args[0] is True:
        return "true"
    elif args[0] is False:
        return "false"
    elif args[0] is None:
        return "null"
    else:
        return str(args[0])


def toInt(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float):
    try:
        if is_hog_datetime(args[0]):
            return int(args[0]["dt"])
        elif is_hog_date(args[0]):
            return (
                datetime.datetime(args[0]["year"], args[0]["month"], args[0]["day"]) - datetime.datetime(1970, 1, 1)
            ).days
        return int(args[0])
    except ValueError:
        return None


def toFloat(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float):
    try:
        if is_hog_datetime(args[0]):
            return float(args[0]["dt"])
        elif is_hog_date(args[0]):
            return float(
                (
                    datetime.datetime(args[0]["year"], args[0]["month"], args[0]["day"]) - datetime.datetime(1970, 1, 1)
                ).days
            )
        return float(args[0])
    except ValueError:
        return None


# ifNull is complied into JUMP instructions. Keeping the function here for backwards compatibility
def ifNull(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float):
    if args[0] is not None:
        return args[0]
    else:
        return args[1]


def empty(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float):
    if isinstance(args[0], bool) or isinstance(args[0], int) or isinstance(args[0], float):
        return False
    return not bool(args[0])


def sleep(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float):
    time.sleep(args[0])
    return None


def print(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float):
    if stdout is not None:
        value = " ".join(map(print_hog_string_output, args))
        stdout.append(value)
    return


def run(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list[Any]:
    if team is None:
        return []
    from posthog.hogql.query import execute_hogql_query

    response = execute_hogql_query(query=args[0], team=team)
    return response.results


def jsonParse(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return json.loads(args[0])


def jsonStringify(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    marked = set()

    def json_safe(obj):
        if isinstance(obj, dict) or isinstance(obj, list) or isinstance(obj, tuple):
            if id(obj) in marked and not is_hog_callable(obj) and not is_hog_closure(obj):
                return None
            else:
                marked.add(id(obj))
                try:
                    if isinstance(obj, dict):
                        if is_hog_callable(obj):
                            return f"fn<{obj['name']}({obj['argCount']})>"
                        if is_hog_closure(obj):
                            return f"fn<{obj['callable']['name']}({obj['callable']['argCount']})>"
                        return {json_safe(k): json_safe(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [json_safe(v) for v in obj]
                    elif isinstance(obj, tuple):
                        return tuple(json_safe(v) for v in obj)
                finally:
                    marked.remove(id(obj))
        return obj

    if len(args) > 1 and isinstance(args[1], int) and args[1] > 0:
        return json.dumps(json_safe(args[0]), indent=args[1])
    return json.dumps(json_safe(args[0]))


def JSONHas(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    obj = args[0]
    path = args[1:]
    current = obj
    for key in path:
        currentParsed = current
        if isinstance(current, str):
            try:
                currentParsed = json.loads(current)
            except json.JSONDecodeError:
                return False
        if isinstance(currentParsed, dict):
            if key not in currentParsed:
                return False
            current = currentParsed[key]
        elif isinstance(currentParsed, list):
            if isinstance(key, int):
                if key < 0:
                    if key < -len(currentParsed):
                        return False
                    current = currentParsed[len(currentParsed) + key]
                elif key == 0:
                    return False
                else:
                    if key > len(currentParsed):
                        return False
                    current = currentParsed[key - 1]
            else:
                return False
        else:
            return False
    return True


def isValidJSON(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    try:
        json.loads(args[0])
        return True
    except json.JSONDecodeError:
        return False


def JSONLength(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> int:
    obj = args[0]
    path = args[1:]
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
    except json.JSONDecodeError:
        return 0
    if not isinstance(obj, dict) and not isinstance(obj, list):
        return 0
    current = get_nested_value(obj, path, nullish=True)
    if isinstance(current, dict) or isinstance(current, list):
        return len(current)
    return 0


def JSONExtractBool(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    obj = args[0]
    path = args[1:]
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
    except json.JSONDecodeError:
        return False
    if len(path) > 0:
        obj = get_nested_value(obj, path, nullish=True)
    if isinstance(obj, bool):
        return obj
    return False


def base64Encode(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    import base64

    return base64.b64encode(args[0].encode()).decode()


def base64Decode(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    import base64

    return base64.b64decode(args[0].encode()).decode()


def encodeURLComponent(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    import urllib.parse

    return urllib.parse.quote(args[0], safe="")


def decodeURLComponent(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    import urllib.parse

    return urllib.parse.unquote(args[0])


def trim(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    char = str(args[1]) if len(args) > 1 and isinstance(args[1], str) else None
    if len(args) > 1:
        if char is None:
            char = " "
        if len(char) > 1:
            return ""
    return args[0].strip(char)


def trimLeft(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    char = str(args[1]) if len(args) > 1 and isinstance(args[1], str) else None
    if len(args) > 1:
        if char is None:
            char = " "
        if len(char) > 1:
            return ""
    return args[0].lstrip(char)


def trimRight(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    char = str(args[1]) if len(args) > 1 and isinstance(args[1], str) else None
    if len(args) > 1:
        if char is None:
            char = " "
        if len(char) > 1:
            return ""
    return args[0].rstrip(char)


def splitByString(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    separator = args[0]
    string = args[1]
    if len(args) > 2 and args[2] is not None:
        parts = string.split(separator, args[2])
        if len(parts) > args[2]:
            return parts[: args[2]]
        return parts
    return string.split(separator)


def generateUUIDv4(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    import uuid

    return str(uuid.uuid4())


def keys(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    obj = args[0]
    if isinstance(obj, dict):
        return list(obj.keys())
    if isinstance(obj, list) or isinstance(obj, tuple):
        return list(range(len(obj)))
    return []


def values(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    obj = args[0]
    if isinstance(obj, dict):
        return list(obj.values())
    if isinstance(obj, list) or isinstance(obj, tuple):
        return list(obj)
    return []


def arrayPushBack(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    arr = args[0]
    item = args[1]
    if not isinstance(arr, list):
        return [item]
    return [*arr, item]


def arrayPushFront(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    arr = args[0]
    item = args[1]
    if not isinstance(arr, list):
        return [item]
    return [item, *arr]


def arrayPopBack(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    arr = args[0]
    if not isinstance(arr, list):
        return []
    return arr[:-1]


def arrayPopFront(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    arr = args[0]
    if not isinstance(arr, list):
        return []
    return arr[1:]


def arraySort(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    arr = args[0]
    if not isinstance(arr, list):
        return []
    return sorted(arr)


def arrayReverse(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    arr = args[0]
    if not isinstance(arr, list):
        return []
    return arr[::-1]


def arrayReverseSort(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    arr = args[0]
    if not isinstance(arr, list):
        return []
    return sorted(arr, reverse=True)


def arrayStringConcat(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    arr = args[0]
    sep = args[1] if len(args) > 1 else ""
    if not isinstance(arr, list):
        return ""
    return sep.join([str(s) for s in arr])


def has(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    if len(args) < 2 or not isinstance(args[0], list):
        return False
    return args[1] in args[0]


def _formatDateTime(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    if len(args) < 2:
        raise ValueError("formatDateTime requires at least 2 arguments")
    return formatDateTime(args[0], args[1], args[2] if len(args) > 2 else None)


def _typeof(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    if args[0] is None:
        return "null"
    elif is_hog_datetime(args[0]):
        return "datetime"
    elif is_hog_date(args[0]):
        return "date"
    elif is_hog_error(args[0]):
        return "error"
    elif is_hog_callable(args[0]) or is_hog_closure(args[0]):
        return "function"
    elif isinstance(args[0], list):
        return "array"
    elif isinstance(args[0], tuple):
        return "tuple"
    elif isinstance(args[0], dict):
        return "object"
    elif args[0] is True or args[0] is False:
        return "boolean"
    elif isinstance(args[0], int):
        return "integer"
    elif isinstance(args[0], float):
        return "float"
    elif isinstance(args[0], str):
        return "string"
    return "unknown"


def apply_interval_to_datetime(dt: dict, interval: dict) -> dict:
    # interval["unit"] in {"day", "hour", "minute", "month"}
    if not (is_hog_date(dt) or is_hog_datetime(dt)):
        raise ValueError("Expected a HogDate or HogDateTime")

    zone = dt["zone"] if is_hog_datetime(dt) else "UTC"
    if is_hog_datetime(dt):
        base_dt = datetime.datetime.utcfromtimestamp(dt["dt"])
        base_dt = pytz.timezone(zone).localize(base_dt)
    else:
        base_dt = datetime.datetime(dt["year"], dt["month"], dt["day"], tzinfo=pytz.timezone(zone))

    value = interval["value"]
    unit = interval["unit"]

    if unit == "day":
        base_dt = base_dt + datetime.timedelta(days=value)
    elif unit == "hour":
        base_dt = base_dt + datetime.timedelta(hours=value)
    elif unit == "minute":
        base_dt = base_dt + datetime.timedelta(minutes=value)
    elif unit == "second":
        base_dt = base_dt + datetime.timedelta(seconds=value)
    elif unit == "month":
        # Add months by incrementing month/year
        # Adding months can overflow year and month boundaries
        # We'll do a rough calculation
        year = base_dt.year
        month = base_dt.month + value
        day = base_dt.day
        # adjust year and month
        year += (month - 1) // 12
        month = ((month - 1) % 12) + 1
        # If day is invalid for the new month, clamp
        # For simplicity, clamp to last valid day of month
        # This matches ClickHouse dateAdd('month',...) behavior
        while True:
            try:
                base_dt = base_dt.replace(year=year, month=month, day=day)
                break
            except ValueError:
                day -= 1
        # no need to add timedelta here
    else:
        raise ValueError(f"Unknown interval unit {unit}")

    if is_hog_date(dt):
        return {
            "__hogDate__": True,
            "year": base_dt.year,
            "month": base_dt.month,
            "day": base_dt.day,
        }
    else:
        return {
            "__hogDateTime__": True,
            "dt": base_dt.timestamp(),
            "zone": zone,
        }


def date_add(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    # dateAdd(unit, amount, datetime)
    # unit: 'second','minute','hour','day','week','month','year'...
    unit = args[0]
    amount = args[1]
    dt = args[2]

    if unit in ["day", "hour", "minute", "second", "month"]:
        pass
    elif unit == "week":
        # dateAdd('week', x, ...) = dateAdd('day', x*7, ...)
        unit = "day"
        amount = amount * 7
    elif unit == "year":
        # year intervals: adding year means 12 months
        unit = "month"
        amount = amount * 12
    else:
        raise ValueError(f"Unsupported interval unit: {unit}")

    interval = to_hog_interval(amount, unit)
    return apply_interval_to_datetime(dt, interval)


def date_diff(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    # dateDiff(unit, start, end)
    unit = args[0]
    start = args[1]
    end = args[2]

    # Convert start/end to aware datetimes
    def to_dt(obj):
        if is_hog_datetime(obj):
            z = obj["zone"]
            return pytz.timezone(z).localize(datetime.datetime.utcfromtimestamp(obj["dt"]))
        elif is_hog_date(obj):
            return pytz.UTC.localize(datetime.datetime(obj["year"], obj["month"], obj["day"]))
        else:
            # try parse string
            d = datetime.datetime.fromisoformat(obj)
            return d.replace(tzinfo=pytz.UTC)

    start_dt = to_dt(start)
    end_dt = to_dt(end)

    diff = end_dt - start_dt
    if unit == "day":
        return diff.days
    elif unit == "hour":
        return int(diff.total_seconds() // 3600)
    elif unit == "minute":
        return int(diff.total_seconds() // 60)
    elif unit == "second":
        return int(diff.total_seconds())
    elif unit == "week":
        return diff.days // 7
    elif unit == "month":
        # approximate: count months difference
        return (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    elif unit == "year":
        return end_dt.year - start_dt.year
    else:
        raise ValueError(f"Unsupported unit for dateDiff: {unit}")


def date_trunc(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    # dateTrunc(unit, datetime)
    unit = args[0]
    dt = args[1]

    if not is_hog_datetime(dt):
        raise ValueError("Expected a DateTime for dateTrunc")

    zone = dt["zone"]
    base_dt = datetime.datetime.utcfromtimestamp(dt["dt"])
    base_dt = pytz.timezone(zone).localize(base_dt)

    if unit == "year":
        truncated = datetime.datetime(base_dt.year, 1, 1, tzinfo=base_dt.tzinfo)
    elif unit == "month":
        truncated = datetime.datetime(base_dt.year, base_dt.month, 1, tzinfo=base_dt.tzinfo)
    elif unit == "day":
        truncated = datetime.datetime(base_dt.year, base_dt.month, base_dt.day, tzinfo=base_dt.tzinfo)
    elif unit == "hour":
        truncated = datetime.datetime(base_dt.year, base_dt.month, base_dt.day, base_dt.hour, tzinfo=base_dt.tzinfo)
    elif unit == "minute":
        truncated = datetime.datetime(
            base_dt.year, base_dt.month, base_dt.day, base_dt.hour, base_dt.minute, tzinfo=base_dt.tzinfo
        )
    else:
        raise ValueError(f"Unsupported unit for dateTrunc: {unit}")

    return {
        "__hogDateTime__": True,
        "dt": truncated.timestamp(),
        "zone": zone,
    }


def coalesce(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    for a in args:
        if a is not None:
            return a
    return None


def assumeNotNull(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    if args[0] is None:
        raise ValueError("Value is null in assumeNotNull")
    return args[0]


def equals(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return args[0] == args[1]


def greater(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return args[0] > args[1]


def greaterOrEquals(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return args[0] >= args[1]


def less(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return args[0] < args[1]


def lessOrEquals(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return args[0] <= args[1]


def notEquals(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return args[0] != args[1]


def not_fn(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return not bool(args[0])


def and_fn(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return all(args)


def or_fn(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return any(args)


def if_fn(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return args[1] if args[0] else args[2]


def in_fn(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return args[0] in args[1] if isinstance(args[1], list | tuple) else False


def min2(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return args[0] if args[0] < args[1] else args[1]


def max2(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return args[0] if args[0] > args[1] else args[1]


def plus(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return args[0] + args[1]


def minus(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return args[0] - args[1]


def multiIf(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    # multiIf(cond1, val1, cond2, val2, ..., default)
    default = args[-1]
    pairs = args[:-1]
    for i in range(0, len(pairs), 2):
        cond = pairs[i]
        val = pairs[i + 1]
        if cond:
            return val
    return default


def floor_fn(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return math.floor(args[0])


def extract(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    # extract(part, datetime)
    # part in { 'year', 'month', 'day', 'hour', 'minute', 'second' }
    part = args[0]
    val = args[1]

    def to_dt(obj):
        if is_hog_datetime(obj):
            z = obj["zone"]
            return pytz.timezone(z).localize(datetime.datetime.utcfromtimestamp(obj["dt"]))
        elif is_hog_date(obj):
            return pytz.UTC.localize(datetime.datetime(obj["year"], obj["month"], obj["day"]))
        else:
            d = datetime.datetime.fromisoformat(obj)
            return d.replace(tzinfo=pytz.UTC)

    dt = to_dt(val)
    if part == "year":
        return dt.year
    elif part == "month":
        return dt.month
    elif part == "day":
        return dt.day
    elif part == "hour":
        return dt.hour
    elif part == "minute":
        return dt.minute
    elif part == "second":
        return dt.second
    else:
        raise ValueError(f"Unknown extract part: {part}")


def round_fn(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return round(args[0])


def startsWith(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> bool:
    return isinstance(args[0], str) and isinstance(args[1], str) and args[0].startswith(args[1])


def substring(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    # substring(str, start, length)
    # start is 1-based.
    s = args[0]
    start = args[1]
    if not isinstance(s, str):
        return ""
    start_idx = start - 1
    length = args[2] if len(args) > 2 else len(s) - start_idx
    if start_idx < 0 or length < 0:
        return ""
    end_idx = start_idx + length
    return s[start_idx:end_idx] if 0 <= start_idx < len(s) else ""


def addDays(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    interval = to_hog_interval(args[1], "day")
    return apply_interval_to_datetime(args[0], interval)


def toIntervalDay(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return to_hog_interval(args[0], "day")


def toIntervalHour(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return to_hog_interval(args[0], "hour")


def toIntervalMinute(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return to_hog_interval(args[0], "minute")


def toIntervalMonth(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return to_hog_interval(args[0], "month")


def toYear(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return extract(["year", args[0]], team, stdout, timeout)


def toMonth_fn(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return extract(["month", args[0]], team, stdout, timeout)


def trunc_to_unit(dt: dict, unit: str, team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> dict:
    # helper for toStartOfDay, etc.
    if not is_hog_datetime(dt):
        if is_hog_date(dt):
            dt = toDateTime(f"{dt['year']:04d}-{dt['month']:02d}-{dt['day']:02d}")
        else:
            raise ValueError("Expected a Date or DateTime")

    return date_trunc([unit, dt], team, stdout, timeout)


def toStartOfDay(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return trunc_to_unit(args[0], "day", team, stdout, timeout)


def toStartOfHour(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return trunc_to_unit(args[0], "hour", team, stdout, timeout)


def toStartOfMonth(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    return trunc_to_unit(args[0], "month", team, stdout, timeout)


def toStartOfWeek(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    dt = args[0]
    if not is_hog_datetime(dt):
        if is_hog_date(dt):
            dt = toDateTime(f"{dt['year']}-{dt['month']:02d}-{dt['day']:02d}")
        else:
            raise ValueError("Expected a Date or DateTime")
    base_dt = datetime.datetime.utcfromtimestamp(dt["dt"])
    zone = dt["zone"]
    base_dt = pytz.timezone(zone).localize(base_dt)
    weekday = base_dt.isoweekday()  # Monday=1, Sunday=7
    start_of_week = base_dt - datetime.timedelta(days=weekday - 1)
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "__hogDateTime__": True,
        "dt": start_of_week.timestamp(),
        "zone": zone,
    }


def toYYYYMM(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    y = toYear([args[0]], team, stdout, timeout)
    m = toMonth_fn([args[0]], team, stdout, timeout)
    return y * 100 + m


def today(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    now_dt = datetime.datetime.now(tz=pytz.UTC)
    return {
        "__hogDate__": True,
        "year": now_dt.year,
        "month": now_dt.month,
        "day": now_dt.day,
    }


def range_fn(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    # range(a,b) -> [a..b-1], range(x) -> [0..x-1]
    if len(args) == 1:
        return list(range(args[0]))
    elif len(args) == 2:
        return list(range(args[0], args[1]))
    else:
        raise ValueError("range function supports 1 or 2 arguments only")


def JSONExtractArrayRaw(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    obj = args[0]
    path = args[1:]
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
    except json.JSONDecodeError:
        return None
    val = get_nested_value(obj, path, True)
    if isinstance(val, list):
        return val
    return None


def JSONExtractFloat(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    obj = args[0]
    path = args[1:]
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
    except json.JSONDecodeError:
        return None
    val = get_nested_value(obj, path, True)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def JSONExtractInt(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    obj = args[0]
    path = args[1:]
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
    except json.JSONDecodeError:
        return None
    val = get_nested_value(obj, path, True)
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def JSONExtractString(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> Any:
    obj = args[0]
    path = args[1:]
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
    except json.JSONDecodeError:
        return None
    val = get_nested_value(obj, path, True)
    return str(val) if val is not None else None


STL: dict[str, STLFunction] = {
    "concat": STLFunction(
        fn=lambda args, team, stdout, timeout: "".join(
            [print_hog_string_output(arg) if arg is not None else "" for arg in args]
        ),
        minArgs=1,
        maxArgs=None,
    ),
    "match": STLFunction(
        fn=lambda args, team, stdout, timeout: False
        if args[1] is None or args[0] is None
        else bool(re.search(re.compile(args[1]), args[0])),
        minArgs=2,
        maxArgs=2,
    ),
    "like": STLFunction(fn=lambda args, team, stdout, timeout: like(args[0], args[1]), minArgs=2, maxArgs=2),
    "ilike": STLFunction(
        fn=lambda args, team, stdout, timeout: like(args[0], args[1], re.IGNORECASE), minArgs=2, maxArgs=2
    ),
    "notLike": STLFunction(fn=lambda args, team, stdout, timeout: not like(args[0], args[1]), minArgs=2, maxArgs=2),
    "notILike": STLFunction(
        fn=lambda args, team, stdout, timeout: not like(args[0], args[1], re.IGNORECASE), minArgs=2, maxArgs=2
    ),
    "toString": STLFunction(fn=toString, minArgs=1, maxArgs=1),
    "toUUID": STLFunction(fn=toString, minArgs=1, maxArgs=1),
    "toInt": STLFunction(fn=toInt, minArgs=1, maxArgs=1),
    "toFloat": STLFunction(fn=toFloat, minArgs=1, maxArgs=1),
    "ifNull": STLFunction(fn=ifNull, minArgs=2, maxArgs=2),
    "isNull": STLFunction(fn=lambda args, team, stdout, timeout: args[0] is None, minArgs=1, maxArgs=1),
    "isNotNull": STLFunction(fn=lambda args, team, stdout, timeout: args[0] is not None, minArgs=1, maxArgs=1),
    "length": STLFunction(fn=lambda args, team, stdout, timeout: len(args[0]), minArgs=1, maxArgs=1),
    "empty": STLFunction(fn=empty, minArgs=1, maxArgs=1),
    "notEmpty": STLFunction(
        fn=lambda args, team, stdout, timeout: not empty(args, team, stdout, timeout), minArgs=1, maxArgs=1
    ),
    "tuple": STLFunction(fn=lambda args, team, stdout, timeout: tuple(args), minArgs=0, maxArgs=None),
    "lower": STLFunction(
        fn=lambda args, team, stdout, timeout: args[0].lower() if args[0] is not None else None, minArgs=1, maxArgs=1
    ),
    "upper": STLFunction(fn=lambda args, team, stdout, timeout: args[0].upper(), minArgs=1, maxArgs=1),
    "reverse": STLFunction(fn=lambda args, team, stdout, timeout: args[0][::-1], minArgs=1, maxArgs=1),
    "print": STLFunction(fn=print, minArgs=0, maxArgs=None),
    "jsonParse": STLFunction(fn=jsonParse, minArgs=1, maxArgs=1),
    "jsonStringify": STLFunction(fn=jsonStringify, minArgs=1, maxArgs=1),
    "JSONHas": STLFunction(fn=JSONHas, minArgs=2, maxArgs=None),
    "isValidJSON": STLFunction(fn=isValidJSON, minArgs=1, maxArgs=1),
    "JSONLength": STLFunction(fn=JSONLength, minArgs=2, maxArgs=None),
    "JSONExtractBool": STLFunction(fn=JSONExtractBool, minArgs=1, maxArgs=None),
    "base64Encode": STLFunction(fn=base64Encode, minArgs=1, maxArgs=1),
    "base64Decode": STLFunction(fn=base64Decode, minArgs=1, maxArgs=1),
    "encodeURLComponent": STLFunction(fn=encodeURLComponent, minArgs=1, maxArgs=1),
    "decodeURLComponent": STLFunction(fn=decodeURLComponent, minArgs=1, maxArgs=1),
    "replaceOne": STLFunction(
        fn=lambda args, team, stdout, timeout: args[0].replace(args[1], args[2], 1), minArgs=3, maxArgs=3
    ),
    "replaceAll": STLFunction(
        fn=lambda args, team, stdout, timeout: args[0].replace(args[1], args[2]), minArgs=3, maxArgs=3
    ),
    "position": STLFunction(
        fn=lambda args, team, stdout, timeout: (args[0].index(str(args[1])) + 1)
        if isinstance(args[0], str) and str(args[1]) in args[0]
        else 0,
        minArgs=2,
        maxArgs=2,
    ),
    "positionCaseInsensitive": STLFunction(
        fn=lambda args, team, stdout, timeout: (args[0].lower().index(str(args[1]).lower()) + 1)
        if isinstance(args[0], str) and str(args[1]).lower() in args[0].lower()
        else 0,
        minArgs=2,
        maxArgs=2,
    ),
    "trim": STLFunction(fn=trim, minArgs=1, maxArgs=2),
    "trimLeft": STLFunction(fn=trimLeft, minArgs=1, maxArgs=2),
    "trimRight": STLFunction(fn=trimRight, minArgs=1, maxArgs=2),
    "splitByString": STLFunction(fn=splitByString, minArgs=2, maxArgs=3),
    "generateUUIDv4": STLFunction(fn=generateUUIDv4, minArgs=0, maxArgs=0),
    "sha256Hex": STLFunction(fn=lambda args, team, stdout, timeout: sha256(args[0]), minArgs=1, maxArgs=1),
    "sha256": STLFunction(
        fn=lambda args, team, stdout, timeout: sha256(args[0], args[1] if len(args) > 1 else "hex"),
        minArgs=1,
        maxArgs=2,
    ),
    "md5Hex": STLFunction(fn=lambda args, team, stdout, timeout: md5(args[0]), minArgs=1, maxArgs=1),
    "md5": STLFunction(
        fn=lambda args, team, stdout, timeout: md5(args[0], args[1] if len(args) > 1 else "hex"), minArgs=1, maxArgs=2
    ),
    "sha256HmacChainHex": STLFunction(
        fn=lambda args, team, stdout, timeout: sha256HmacChain(args[0], "hex"),
        minArgs=1,
        maxArgs=1,
    ),
    "sha256HmacChain": STLFunction(
        fn=lambda args, team, stdout, timeout: sha256HmacChain(args[0], args[1] if len(args) > 1 else "hex"),
        minArgs=1,
        maxArgs=2,
    ),
    "isIPAddressInRange": STLFunction(
        fn=lambda args, team, stdout, timeout: isIPAddressInRange(args[0], args[1]), minArgs=2, maxArgs=2
    ),
    "keys": STLFunction(fn=keys, minArgs=1, maxArgs=1),
    "values": STLFunction(fn=values, minArgs=1, maxArgs=1),
    "indexOf": STLFunction(
        fn=lambda args, team, stdout, timeout: (args[0].index(args[1]) + 1)
        if isinstance(args[0], list) and args[1] in args[0]
        else 0,
        minArgs=2,
        maxArgs=2,
    ),
    "arrayPushBack": STLFunction(fn=arrayPushBack, minArgs=2, maxArgs=2),
    "arrayPushFront": STLFunction(fn=arrayPushFront, minArgs=2, maxArgs=2),
    "arrayPopBack": STLFunction(fn=arrayPopBack, minArgs=1, maxArgs=1),
    "arrayPopFront": STLFunction(fn=arrayPopFront, minArgs=1, maxArgs=1),
    "arraySort": STLFunction(fn=arraySort, minArgs=1, maxArgs=1),
    "arrayReverse": STLFunction(fn=arrayReverse, minArgs=1, maxArgs=1),
    "arrayReverseSort": STLFunction(fn=arrayReverseSort, minArgs=1, maxArgs=1),
    "arrayStringConcat": STLFunction(fn=arrayStringConcat, minArgs=1, maxArgs=2),
    "has": STLFunction(fn=has, minArgs=2, maxArgs=2),
    "now": STLFunction(fn=lambda args, team, stdout, timeout: now(), minArgs=0, maxArgs=0),
    "toUnixTimestamp": STLFunction(
        fn=lambda args, team, stdout, timeout: toUnixTimestamp(args[0], args[1] if len(args) > 1 else None),
        minArgs=1,
        maxArgs=2,
    ),
    "fromUnixTimestamp": STLFunction(
        fn=lambda args, team, stdout, timeout: fromUnixTimestamp(args[0]), minArgs=1, maxArgs=1
    ),
    "toUnixTimestampMilli": STLFunction(
        fn=lambda args, team, stdout, timeout: toUnixTimestampMilli(args[0]), minArgs=1, maxArgs=2
    ),
    "fromUnixTimestampMilli": STLFunction(
        fn=lambda args, team, stdout, timeout: fromUnixTimestampMilli(args[0]), minArgs=1, maxArgs=1
    ),
    "toTimeZone": STLFunction(
        fn=lambda args, team, stdout, timeout: toTimeZone(args[0], args[1]), minArgs=2, maxArgs=2
    ),
    "toDate": STLFunction(fn=lambda args, team, stdout, timeout: toDate(args[0]), minArgs=1, maxArgs=1),
    "toDateTime": STLFunction(fn=lambda args, team, stdout, timeout: toDateTime(args[0]), minArgs=1, maxArgs=2),
    "formatDateTime": STLFunction(fn=_formatDateTime, minArgs=2, maxArgs=3),
    "HogError": STLFunction(
        fn=lambda args, team, stdout, timeout: new_hog_error(args[0], args[1], args[2] if len(args) > 2 else None),
        minArgs=1,
        maxArgs=3,
    ),
    "Error": STLFunction(
        fn=lambda args, team, stdout, timeout: new_hog_error(
            "Error", args[0] if len(args) > 0 else None, args[1] if len(args) > 1 else None
        ),
        minArgs=0,
        maxArgs=2,
    ),
    "RetryError": STLFunction(
        fn=lambda args, team, stdout, timeout: new_hog_error("RetryError", args[0], args[1] if len(args) > 1 else None),
        minArgs=0,
        maxArgs=2,
    ),
    "NotImplementedError": STLFunction(
        fn=lambda args, team, stdout, timeout: new_hog_error(
            "NotImplementedError", args[0], args[1] if len(args) > 1 else None
        ),
        minArgs=0,
        maxArgs=2,
    ),
    "typeof": STLFunction(fn=_typeof, minArgs=1, maxArgs=1),
    "JSONExtractArrayRaw": STLFunction(fn=JSONExtractArrayRaw, minArgs=1),
    "JSONExtractFloat": STLFunction(fn=JSONExtractFloat, minArgs=1),
    "JSONExtractInt": STLFunction(fn=JSONExtractInt, minArgs=1),
    "JSONExtractString": STLFunction(fn=JSONExtractString, minArgs=1),
    "and": STLFunction(fn=and_fn, minArgs=2, maxArgs=2),
    "addDays": STLFunction(fn=addDays, minArgs=2, maxArgs=2),
    "assumeNotNull": STLFunction(fn=assumeNotNull, minArgs=1, maxArgs=1),
    "coalesce": STLFunction(fn=coalesce, minArgs=1, maxArgs=None),
    "dateAdd": STLFunction(fn=date_add, minArgs=3, maxArgs=3),
    "dateDiff": STLFunction(fn=date_diff, minArgs=3, maxArgs=3),
    "dateTrunc": STLFunction(fn=date_trunc, minArgs=2, maxArgs=2),
    "equals": STLFunction(fn=equals, minArgs=2, maxArgs=2),
    "extract": STLFunction(fn=extract, minArgs=2, maxArgs=2),
    "floor": STLFunction(fn=floor_fn, minArgs=1, maxArgs=1),
    "greater": STLFunction(fn=greater, minArgs=2, maxArgs=2),
    "greaterOrEquals": STLFunction(fn=greaterOrEquals, minArgs=2, maxArgs=2),
    "if": STLFunction(fn=if_fn, minArgs=3, maxArgs=3),
    "in": STLFunction(fn=in_fn, minArgs=2, maxArgs=2),
    "less": STLFunction(fn=less, minArgs=2, maxArgs=2),
    "lessOrEquals": STLFunction(fn=lessOrEquals, minArgs=2, maxArgs=2),
    "min2": STLFunction(fn=min2, minArgs=2, maxArgs=2),
    "max2": STLFunction(fn=max2, minArgs=2, maxArgs=2),
    "minus": STLFunction(fn=minus, minArgs=2, maxArgs=2),
    "multiIf": STLFunction(fn=multiIf, minArgs=3),
    "not": STLFunction(fn=not_fn, minArgs=1, maxArgs=1),
    "notEquals": STLFunction(fn=notEquals, minArgs=2, maxArgs=2),
    "or": STLFunction(fn=or_fn, minArgs=2, maxArgs=2),
    "plus": STLFunction(fn=plus, minArgs=2, maxArgs=2),
    "range": STLFunction(fn=range_fn, minArgs=1, maxArgs=2),
    "round": STLFunction(fn=round_fn, minArgs=1, maxArgs=1),
    "startsWith": STLFunction(fn=startsWith, minArgs=2, maxArgs=2),
    "substring": STLFunction(fn=substring, minArgs=2, maxArgs=3),
    "toIntervalDay": STLFunction(fn=toIntervalDay, minArgs=1, maxArgs=1),
    "toIntervalHour": STLFunction(fn=toIntervalHour, minArgs=1, maxArgs=1),
    "toIntervalMinute": STLFunction(fn=toIntervalMinute, minArgs=1, maxArgs=1),
    "toIntervalMonth": STLFunction(fn=toIntervalMonth, minArgs=1, maxArgs=1),
    "toMonth": STLFunction(fn=toMonth_fn, minArgs=1, maxArgs=1),
    "toStartOfDay": STLFunction(fn=toStartOfDay, minArgs=1, maxArgs=1),
    "toStartOfHour": STLFunction(fn=toStartOfHour, minArgs=1, maxArgs=1),
    "toStartOfMonth": STLFunction(fn=toStartOfMonth, minArgs=1, maxArgs=1),
    "toStartOfWeek": STLFunction(fn=toStartOfWeek, minArgs=1, maxArgs=1),
    "toYYYYMM": STLFunction(fn=toYYYYMM, minArgs=1, maxArgs=1),
    "toYear": STLFunction(fn=toYear, minArgs=1, maxArgs=1),
    "today": STLFunction(fn=today, minArgs=0, maxArgs=0),
    # only in python, async function in nodejs
    "sleep": STLFunction(fn=sleep, minArgs=1, maxArgs=1),
    "run": STLFunction(fn=run, minArgs=1, maxArgs=1),
    # Cohort membership functions
    "inCohort": STLFunction(fn=inCohort, minArgs=2, maxArgs=2),
    "notInCohort": STLFunction(fn=notInCohort, minArgs=2, maxArgs=2),
}
