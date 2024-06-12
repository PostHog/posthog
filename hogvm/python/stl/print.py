import re

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


def print_hog_value(obj):
    if isinstance(obj, list):
        return f"[{', '.join(map(print_hog_value, obj))}]"
    if isinstance(obj, dict):
        return f"{{{', '.join([f'{print_hog_value(key)}: {print_hog_value(value)}' for key, value in obj.items()])}}}"
    if isinstance(obj, tuple):
        if len(obj) < 2:
            return f"tuple({', '.join(map(print_hog_value, obj))})"
        return f"({', '.join(map(print_hog_value, obj))})"
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
