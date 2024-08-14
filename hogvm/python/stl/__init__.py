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
from ..objects import is_hog_error, new_hog_error
from ..utils import like

if TYPE_CHECKING:
    from posthog.models import Team


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
            if id(obj) in marked:
                return None
            else:
                marked.add(id(obj))
                try:
                    if isinstance(obj, dict):
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
    if len(args) > 1 and len(args[1]) > 1:
        return ""
    return args[0].strip(args[1] if len(args) > 1 else None)


def trimLeft(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    if len(args) > 1 and len(args[1]) > 1:
        return ""
    return args[0].lstrip(args[1] if len(args) > 1 else None)


def trimRight(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> str:
    if len(args) > 1 and len(args[1]) > 1:
        return ""
    return args[0].rstrip(args[1] if len(args) > 1 else None)


def splitByString(args: list[Any], team: Optional["Team"], stdout: Optional[list[str]], timeout: float) -> list:
    separator = args[0]
    string = args[1]
    if len(args) > 2:
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


STL: dict[str, Callable[[list[Any], Optional["Team"], list[str] | None, float], Any]] = {
    "concat": lambda args, team, stdout, timeout: "".join(
        [print_hog_string_output(arg) if arg is not None else "" for arg in args]
    ),
    "match": lambda args, team, stdout, timeout: bool(re.search(re.compile(args[1]), args[0])),
    "like": lambda args, team, stdout, timeout: like(args[0], args[1]),
    "ilike": lambda args, team, stdout, timeout: like(args[0], args[1], re.IGNORECASE),
    "notLike": lambda args, team, stdout, timeout: not like(args[0], args[1]),
    "notILike": lambda args, team, stdout, timeout: not like(args[0], args[1], re.IGNORECASE),
    "toString": toString,
    "toUUID": toString,
    "toInt": toInt,
    "toFloat": toFloat,
    "ifNull": ifNull,
    "length": lambda args, team, stdout, timeout: len(args[0]),
    "empty": lambda args, team, stdout, timeout: not bool(args[0]),
    "notEmpty": lambda args, team, stdout, timeout: bool(args[0]),
    "tuple": lambda args, team, stdout, timeout: tuple(args),
    "lower": lambda args, team, stdout, timeout: args[0].lower(),
    "upper": lambda args, team, stdout, timeout: args[0].upper(),
    "reverse": lambda args, team, stdout, timeout: args[0][::-1],
    "sleep": sleep,
    "print": print,
    "run": run,
    "jsonParse": jsonParse,
    "jsonStringify": jsonStringify,
    "base64Encode": base64Encode,
    "base64Decode": base64Decode,
    "encodeURLComponent": encodeURLComponent,
    "decodeURLComponent": decodeURLComponent,
    "replaceOne": lambda args, team, stdout, timeout: args[0].replace(args[1], args[2], 1),
    "replaceAll": lambda args, team, stdout, timeout: args[0].replace(args[1], args[2]),
    "trim": trim,
    "trimLeft": trimLeft,
    "trimRight": trimRight,
    "splitByString": splitByString,
    "generateUUIDv4": generateUUIDv4,
    "sha256Hex": lambda args, team, stdout, timeout: sha256Hex(args[0]),
    "md5Hex": lambda args, team, stdout, timeout: md5Hex(args[0]),
    "sha256HmacChainHex": lambda args, team, stdout, timeout: sha256HmacChainHex(args[0]),
    "keys": keys,
    "values": values,
    "arrayPushBack": arrayPushBack,
    "arrayPushFront": arrayPushFront,
    "arrayPopBack": arrayPopBack,
    "arrayPopFront": arrayPopFront,
    "arraySort": arraySort,
    "arrayReverse": arrayReverse,
    "arrayReverseSort": arrayReverseSort,
    "arrayStringConcat": arrayStringConcat,
    "has": has,
    "now": lambda args, team, stdout, timeout: now(),
    "toUnixTimestamp": lambda args, team, stdout, timeout: toUnixTimestamp(args[0], args[1] if len(args) > 1 else None),
    "fromUnixTimestamp": lambda args, team, stdout, timeout: fromUnixTimestamp(args[0]),
    "toUnixTimestampMilli": lambda args, team, stdout, timeout: toUnixTimestampMilli(args[0]),
    "fromUnixTimestampMilli": lambda args, team, stdout, timeout: fromUnixTimestampMilli(args[0]),
    "toTimeZone": lambda args, team, stdout, timeout: toTimeZone(args[0], args[1]),
    "toDate": lambda args, team, stdout, timeout: toDate(args[0]),
    "toDateTime": lambda args, team, stdout, timeout: toDateTime(args[0]),
    "formatDateTime": _formatDateTime,
    "HogError": lambda args, team, stdout, timeout: new_hog_error(args[0], args[1], args[2] if len(args) > 2 else None),
    "Error": lambda args, team, stdout, timeout: new_hog_error("Error", args[0], args[1] if len(args) > 1 else None),
    "RetryError": lambda args, team, stdout, timeout: new_hog_error(
        "RetryError", args[0], args[1] if len(args) > 1 else None
    ),
    "NotImplementedError": lambda args, team, stdout, timeout: new_hog_error(
        "NotImplementedError", args[0], args[1] if len(args) > 1 else None
    ),
}


MIN_ARGS_INCLUDING_OPTIONAL = {
    "HogError": 3,
    "Error": 2,
    "RetryError": 2,
    "NotImplementedError": 2,
}
