import re

# Copied from clickhouse_driver.util.escape, adapted from single quotes to backquotes.
backquote_escape_chars_map = {
    "\b": "\\b",
    "\f": "\\f",
    "\r": "\\r",
    "\n": "\\n",
    "\t": "\\t",
    "\0": "\\0",
    "\a": "\\a",
    "\v": "\\v",
    "\\": "\\\\",
    "`": "\\`",
}


def sanitize_clickhouse_identifier(identifier: str) -> str:
    if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", identifier):
        return identifier

    return "`%s`" % "".join(backquote_escape_chars_map.get(c, c) for c in identifier)
