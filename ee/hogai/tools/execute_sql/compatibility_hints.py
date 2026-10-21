"""Turn a known HogQL compatibility rejection into the rewrite that HogQL accepts.

HogQL is close enough to ClickHouse SQL that callers write plain ClickHouse and get a rejection
that states the rule but not the way out: ``greatest`` is binary here, ``LIKE`` takes no ``\\_``
escape, and ``CAST`` knows a short list of type names. The error names the construct, so the caller
knows which call failed, and then retries the same shape because nothing told it what HogQL accepts
instead. Each rule below adds the one accepted rewrite for a failure we see repeatedly.
"""

import re

# ClickHouse takes any number of arguments for these; HogQL caps both at 2, and nesting is exact
# rather than approximate because both are associative. `test_nesting_rewrite_is_actually_accepted`
# pins the cap against the validator, so lifting it in `mapping.py` fails a test rather than leaving
# this advice quietly wrong.
NESTABLE_BINARY_FUNCTIONS = ("greatest", "least")

# The type names `visit_type_cast` accepts, one per target type. Anything else — including every
# width-suffixed ClickHouse spelling such as `Float64` — is rejected.
ACCEPTED_CAST_TYPES = ("Int", "Float", "String", "Boolean", "Date", "DateTime")

# ClickHouse spellings mapped onto the accepted name, longest prefix first so `datetime64` resolves
# to DateTime and `date32` to Date. Matching a caller's spelling against this list beats deriving it
# from ACCEPTED_CAST_TYPES, which cannot tell `date32` from an abbreviation of `datetime`.
_CAST_TYPE_PREFIXES = (
    ("datetime", "DateTime"),
    ("timestamp", "DateTime"),
    ("date", "Date"),
    ("string", "String"),
    ("float", "Float"),
    ("double", "Float"),
    ("bool", "Boolean"),
    ("int", "Int"),
)

# Decimal is deliberately absent above. HogQL accepts no Decimal cast, but Float is the wrong
# substitute: it swaps exact decimal arithmetic for binary floating point, which moves the result of
# a money query rather than failing. `toDecimal` is the exact equivalent, so point at that instead.
_DECIMAL_PREFIX = "decimal"

# ClickHouse decorations that carry no meaning for a HogQL cast.
_CAST_WRAPPER_RE = re.compile(r"^(?:nullable|lowcardinality)\((.*)\)$")
_CAST_WIDTH_RE = re.compile(r"^u?(.+?)\d*$")

_TOO_MANY_ARGS_RE = re.compile(r"Function '(\w+)' expects (\d+) arguments?, found (\d+)")
_BAD_ESCAPE_RE = re.compile(r"unrecognised escape '\\(.)'")
_BAD_CAST_RE = re.compile(r"Unsupported type cast to '([^']{1,40})'")


def _nested_call(name: str, arity: int) -> str:
    """Render the accepted nesting for an over-arity call, e.g. `greatest(x1, greatest(x2, x3))`."""
    call = f"x{arity}"
    for position in range(arity - 1, 0, -1):
        call = f"{name}(x{position}, {call})"
    return call


def _normalize_cast_type(type_name: str) -> str:
    """Strip the decorations that carry no meaning for a HogQL cast: wrappers, width, unsignedness."""
    normalized = type_name.strip().lower()
    if wrapper := _CAST_WRAPPER_RE.match(normalized):
        return _normalize_cast_type(wrapper.group(1))
    width = _CAST_WIDTH_RE.match(normalized)
    return width.group(1) if width else normalized


def suggest_cast_type(type_name: str) -> str | None:
    """Map a rejected ClickHouse cast type name onto the HogQL spelling, if one matches."""
    bare = _normalize_cast_type(type_name)
    for prefix, accepted in _CAST_TYPE_PREFIXES:
        if bare.startswith(prefix):
            return accepted
    return None


def build_compatibility_hint(error_message: str) -> str | None:
    """Build an additive hint naming the accepted rewrite, or None if no rule matches."""
    for rule in (_arity_rewrite, _escape_rewrite, _cast_rewrite):
        rewrite = rule(error_message)
        if rewrite is not None:
            return f"<hogql_compatibility_hint>\n{rewrite}\n</hogql_compatibility_hint>"
    return None


def _arity_rewrite(error_message: str) -> str | None:
    match = _TOO_MANY_ARGS_RE.search(error_message)
    if match is None:
        return None
    name, expected, found = match.group(1), int(match.group(2)), int(match.group(3))
    if name not in NESTABLE_BINARY_FUNCTIONS or expected != 2 or found <= 2:
        return None
    return (
        f"`{name}` takes exactly 2 arguments in HogQL, unlike ClickHouse. Nest two-argument calls "
        f"instead: {_nested_call(name, found)}."
    )


def _escape_rewrite(error_message: str) -> str | None:
    match = _BAD_ESCAPE_RE.search(error_message)
    if match is None:
        return None
    char = match.group(1)
    return (
        f"HogQL string literals do not define the escape `\\{char}`. To match a literal `{char}` "
        f"with LIKE, escape the backslash itself: '%\\\\{char}%'. To match a plain substring with no "
        "wildcards at all, `position(haystack, needle) > 0` avoids escaping entirely."
    )


def _cast_rewrite(error_message: str) -> str | None:
    match = _BAD_CAST_RE.search(error_message)
    if match is None:
        return None
    type_name = match.group(1)
    lead = (
        f"HogQL casts do not take width-suffixed ClickHouse type names such as `{type_name}`. "
        f"Accepted type names are: {', '.join(ACCEPTED_CAST_TYPES)}."
    )
    if _normalize_cast_type(type_name).startswith(_DECIMAL_PREFIX):
        return (
            f"{lead} None of them holds an exact decimal, so do not cast to Float here: that changes "
            "the arithmetic and can move the result. Use `toDecimal(x, scale)` instead."
        )
    suggestion = suggest_cast_type(type_name)
    return f"{lead} Use `CAST(x AS {suggestion})` or `to{suggestion}(x)`." if suggestion else lead
