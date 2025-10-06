import re

from common.hogvm.python.objects import is_hog_callable, is_hog_closure, is_hog_date, is_hog_datetime, is_hog_error

# Copied from clickhouse_driver.util.escape, adapted only from single quotes to backquotes.
escape_chars_map = {
    "\b": "\\b",
    "\f": "\\f",
    "\r": "\\r",
    "\n": "\\n",
    "\t": "\\t",
    "\0": "\\0",
    "\a": "\\a",
    "\v": "\\v",
    "\\": "\\\\",
}
singlequote_escape_chars_map = {**escape_chars_map, "'": "\\'"}
backquote_escape_chars_map = {**escape_chars_map, "`": "\\`"}


# Copied from clickhouse_driver.util.escape_param
def escape_string(value: str) -> str:
    return "'{}'".format("".join(singlequote_escape_chars_map.get(c, c) for c in str(value)))


# Copied from clickhouse_driver.util.escape, adapted from single quotes to backquotes. Added a $.
def escape_identifier(identifier: str | int) -> str:
    if isinstance(identifier, int):  # In HogQL we allow integers as identifiers to access array elements
        return str(identifier)
    # HogQL allows dollars in the identifier.
    if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", identifier):
        return identifier
    return "`{}`".format("".join(backquote_escape_chars_map.get(c, c) for c in identifier))


def print_hog_value(obj, marked: set | None = None):
    if marked is None:
        marked = set()
    if isinstance(obj, dict) and is_hog_datetime(obj):
        return f"DateTime({float(obj['dt'])}, {escape_string(obj['zone'] or 'UTC')})"
    if isinstance(obj, dict) and is_hog_date(obj):
        return f"Date({obj['year']}, {obj['month']}, {obj['day']})"
    if isinstance(obj, dict) and is_hog_error(obj):
        return (
            f"{obj['type']}({print_hog_value(obj['message'])}"
            + (f", {print_hog_value(obj['payload'])}" if "payload" in obj and obj["payload"] is not None else "")
            + ")"
        )
    if isinstance(obj, dict) and is_hog_closure(obj):
        return print_hog_value(obj["callable"], marked)
    if isinstance(obj, dict) and is_hog_callable(obj):
        return f"fn<{escape_identifier(obj.get('name', 'lambda'))}({print_hog_value(obj['argCount'])})>"
    if isinstance(obj, list) or isinstance(obj, dict) or isinstance(obj, tuple):
        if id(obj) in marked:
            return "null"
        marked.add(id(obj))
        try:
            if isinstance(obj, list):
                return f"[{', '.join([print_hog_value(o, marked) for o in obj])}]"
            if isinstance(obj, dict):
                return f"{{{', '.join([f'{print_hog_value(key, marked)}: {print_hog_value(value, marked)}' for key, value in obj.items()])}}}"
            if isinstance(obj, tuple):
                if len(obj) < 2:
                    return f"tuple({', '.join([print_hog_value(o, marked) for o in obj])})"
                return f"({', '.join([print_hog_value(o, marked) for o in obj])})"
        finally:
            marked.remove(id(obj))

    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if obj is None:
        return "null"
    if isinstance(obj, str):
        return escape_string(obj)
    return str(obj)


def print_hog_string_output(obj):
    if isinstance(obj, str):
        return str(obj)
    return print_hog_value(obj)
