import dataclasses
import datetime
import time
from typing import Any, Optional, TYPE_CHECKING
from collections.abc import Callable
import re
import json

import pytz

from .print import print_hog_string_output
from .date import (
    now,
    toUnixTimestamp,
    fromUnixTimestamp,
    toUnixTimestampMilli,
    fromUnixTimestampMilli,
    toTimeZone,
    toDate,
    toDateTime,
    formatDateTime,
    is_hog_datetime,
    is_hog_date,
)
from .crypto import sha256Hex, md5Hex, sha256HmacChainHex
from ..objects import is_hog_error, new_hog_error, is_hog_callable, is_hog_closure
from ..utils import like

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


STL: dict[str, STLFunction] = {
    "concat": STLFunction(
        fn=lambda args, team, stdout, timeout: "".join(
            [print_hog_string_output(arg) if arg is not None else "" for arg in args]
        ),
        minArgs=1,
        maxArgs=None,
    ),
    "match": STLFunction(
        fn=lambda args, team, stdout, timeout: bool(re.search(re.compile(args[1]), args[0])), minArgs=2, maxArgs=2
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
    "length": STLFunction(fn=lambda args, team, stdout, timeout: len(args[0]), minArgs=1, maxArgs=1),
    "empty": STLFunction(fn=empty, minArgs=1, maxArgs=1),
    "notEmpty": STLFunction(
        fn=lambda args, team, stdout, timeout: not empty(args, team, stdout, timeout), minArgs=1, maxArgs=1
    ),
    "tuple": STLFunction(fn=lambda args, team, stdout, timeout: tuple(args), minArgs=0, maxArgs=None),
    "lower": STLFunction(fn=lambda args, team, stdout, timeout: args[0].lower(), minArgs=1, maxArgs=1),
    "upper": STLFunction(fn=lambda args, team, stdout, timeout: args[0].upper(), minArgs=1, maxArgs=1),
    "reverse": STLFunction(fn=lambda args, team, stdout, timeout: args[0][::-1], minArgs=1, maxArgs=1),
    "print": STLFunction(fn=print, minArgs=0, maxArgs=None),
    "jsonParse": STLFunction(fn=jsonParse, minArgs=1, maxArgs=1),
    "jsonStringify": STLFunction(fn=jsonStringify, minArgs=1, maxArgs=1),
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
    "sha256Hex": STLFunction(fn=lambda args, team, stdout, timeout: sha256Hex(args[0]), minArgs=1, maxArgs=1),
    "md5Hex": STLFunction(fn=lambda args, team, stdout, timeout: md5Hex(args[0]), minArgs=1, maxArgs=1),
    "sha256HmacChainHex": STLFunction(
        fn=lambda args, team, stdout, timeout: sha256HmacChainHex(args[0]), minArgs=1, maxArgs=1
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
    # only in python, async function in nodejs
    "sleep": STLFunction(fn=sleep, minArgs=1, maxArgs=1),
    "run": STLFunction(fn=run, minArgs=1, maxArgs=1),
}
