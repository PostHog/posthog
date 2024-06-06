import time
from typing import Any, Optional
from collections.abc import Callable
import re
import json

from posthog.hogql.query import execute_hogql_query
from posthog.models import Team


def concat(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    def _to_concat_arg(arg) -> str:
        if arg is None:
            return ""
        if arg is True:
            return "true"
        if arg is False:
            return "false"
        return str(arg)

    return "".join([_to_concat_arg(arg) for arg in args])


def match(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    return bool(re.search(re.compile(args[1]), args[0]))


def toString(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    if args[0] is True:
        return "true"
    elif args[0] is False:
        return "false"
    elif args[0] is None:
        return "null"
    else:
        return str(args[0])


def toInt(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    try:
        return int(args[0]) if name == "toInt" else float(args[0])
    except ValueError:
        return None


def ifNull(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    if args[0] is not None:
        return args[0]
    else:
        return args[1]


def length(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    return len(args[0])


def empty(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    return not bool(args[0])


def notEmpty(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    return bool(args[0])


def lower(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    return args[0].lower()


def upper(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    return args[0].upper()


def reverse(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    return args[0][::-1]


def sleep(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    time.sleep(args[0])
    return None


def print(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int):
    if stdout is not None:
        stdout.append(f"{(' '.join(map(str, args)))}\n")
    return


def run(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int) -> list[Any]:
    if team is None:
        return []
    response = execute_hogql_query(query=args[0], team=team)
    return response.results


def jsonParse(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int) -> Any:
    return json.loads(args[0])


def jsonStringify(name: str, args: list[Any], team: Optional[Team], stdout: Optional[list[str]], timeout: int) -> str:
    if len(args) > 1 and isinstance(args[1], int) and args[1] > 0:
        return json.dumps(args[0], indent=args[1])
    return json.dumps(args[0])


STL: dict[str, Callable[[str, list[Any], Team | None, list[str] | None, int], Any]] = {
    "concat": concat,
    "match": match,
    "toString": toString,
    "toUUID": toString,
    "toInt": toInt,
    "toFloat": toInt,
    "ifNull": ifNull,
    "length": length,
    "empty": empty,
    "notEmpty": notEmpty,
    "lower": lower,
    "upper": upper,
    "reverse": reverse,
    "sleep": sleep,
    "print": print,
    "run": run,
    "jsonParse": jsonParse,
    "jsonStringify": jsonStringify,
}
