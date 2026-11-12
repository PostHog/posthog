import re
import math
from typing import Final

from ..message_normalizer.run_limits import check_time_limit

_TOKENS_PER_CLOCK_CHECK: Final = 10_000

# A JSON string, which is skipped, or a JSON number literal. The string loop is possessive because a backtracking
# loop keeps one stack entry per character of the string.
_JSON_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*+"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', re.ASCII)
_DECIMAL = re.compile(r"(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?", re.ASCII)


def has_lossy_number(json_text: str) -> bool:
    """Whether the browser's `JSON.parse` would change any number in this JSON text, by rounding it or making it null."""
    for count, match in enumerate(_JSON_TOKEN.finditer(json_text)):
        # The scan runs Python code for every token, so text of up to the parse cap can take longer than the deadline.
        if count % _TOKENS_PER_CLOCK_CHECK == 0:
            check_time_limit()
        token = match.group()
        if not token.startswith('"') and _loses_precision(token):
            return True
    return False


def _loses_precision(literal: str) -> bool:
    # Python's float and the browser's number are both IEEE doubles, and both print the shortest digits that round-trip.
    parsed = float(literal)
    return not math.isfinite(parsed) or _canonical_decimal(literal) != _canonical_decimal(repr(parsed))


def _canonical_decimal(literal: str) -> str:
    """The exact value of a number literal as sign, significant digits and exponent, so equal values compare equal."""
    match = _DECIMAL.fullmatch(literal)
    if match is None:
        return literal
    sign, integer, fraction, exponent = match.group(1), match.group(2), match.group(3) or "", match.group(4) or "0"
    digits = (integer + fraction).lstrip("0")
    significant = digits.rstrip("0")
    try:
        power = int(exponent) - len(fraction) + len(digits) - len(significant)
    except ValueError:
        # Python refuses to read an integer past 4,300 digits, and no double can hold that exponent anyway.
        return literal
    return f"{sign}{significant}e{power}" if significant else "0"
