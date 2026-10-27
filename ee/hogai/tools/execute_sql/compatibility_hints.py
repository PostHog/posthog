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

# ClickHouse rejections that reach the caller unchanged. Each names the construct and the rule it
# broke, but not the HogQL shape that satisfies the rule.
# A property aggregate prints as a long JSONExtract chain, so the captured expression can run to
# hundreds of characters; it is shortened for display, not for matching.
_NESTED_AGGREGATE_RE = re.compile(r"Aggregate function (.{1,1000}?) is found inside another aggregate function")
_HOGQL_NESTED_AGGREGATE_RE = re.compile(r"Aggregation '(\w+)' cannot be nested inside another aggregation")
_AGGREGATE_IN_FILTER_RE = re.compile(r"Aggregate function (.{1,1000}?) is found in (WHERE|PREWHERE)")
_NOT_AN_AGGREGATE_RE = re.compile(r"Column (.{1,1000}?) is not under aggregate function and not in GROUP BY")
# ClickHouse prints the rejected types and the function in four shapes: `type of first argument of
# function f`, `type of argument #1 'name' of function f`, `type of argument for aggregate function
# f`, and `of arguments (type, type) of function f`.
_ILLEGAL_ARGUMENT_TYPE_RES = (
    re.compile(
        r"Illegal types? (.{1,120}?) of (?:(?:\w+ )?arguments?|argument #\d+(?: '[^']{0,60}')?) of function (\w+)"
    ),
    re.compile(r"Illegal types? (.{1,120}?) of arguments? for aggregate function (\w+)(?=[.,]|\s*\(|\s*$)"),
    re.compile(r"Illegal types? of arguments? \((.{1,120}?)\) of function `?(\w+)"),
)
# A comparison or IN between a string property and a number fails before any function is named.
_NO_COMMON_TYPE_RE = re.compile(r"There is no supertype for types (.{1,120}?) because")
_DISPLAY_LIMIT = 80
_TYPE_WRAPPER_RE = re.compile(r"(?:Nullable|LowCardinality)\(([^()]*)\)")
# A column ClickHouse names back to us is HogQL only when it is a plain field chain. Printed
# expressions and resolved names such as `events__person.properties___email` are not.
_HOGQL_FIELD_CHAIN_RE = re.compile(r"^[A-Za-z_$][\w.$]*$")


def _display(expression: str) -> str:
    return expression if len(expression) <= _DISPLAY_LIMIT else f"{expression[: _DISPLAY_LIMIT - 3]}..."


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
    for rule in (
        _arity_rewrite,
        _escape_rewrite,
        _cast_rewrite,
        _nested_aggregate_rewrite,
        _aggregate_in_filter_rewrite,
        _not_an_aggregate_rewrite,
        _argument_type_rewrite,
        _no_common_type_rewrite,
    ):
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


def _nested_aggregate_rewrite(error_message: str) -> str | None:
    match = _NESTED_AGGREGATE_RE.search(error_message) or _HOGQL_NESTED_AGGREGATE_RE.search(error_message)
    if match is None:
        return None
    return (
        f"`{_display(match.group(1))}` is nested inside another aggregate, which is not allowed. Aggregate per "
        "group in a subquery first, then aggregate that result in the outer query: "
        "SELECT avg(n) FROM (SELECT person_id, count() AS n FROM events GROUP BY person_id)."
    )


def _aggregate_in_filter_rewrite(error_message: str) -> str | None:
    match = _AGGREGATE_IN_FILTER_RE.search(error_message)
    if match is None:
        return None
    return (
        f"`{_display(match.group(1))}` is an aggregate, so it cannot filter rows in {match.group(2)}. Put the condition "
        "in HAVING after GROUP BY, or compute the aggregate in a subquery and filter its result."
    )


def _not_an_aggregate_rewrite(error_message: str) -> str | None:
    match = _NOT_AN_AGGREGATE_RE.search(error_message)
    if match is None:
        return None
    column = match.group(1).strip("`")
    if _HOGQL_FIELD_CHAIN_RE.match(column) and "__" not in column:
        return (
            f"`{column}` is selected without an aggregate in a query that has GROUP BY. Add it to GROUP BY, "
            f"or wrap it in an aggregate such as any({column}) or max({column})."
        )
    return (
        "A selected expression is not aggregated and not in GROUP BY. Add it to GROUP BY, or wrap it in an "
        "aggregate such as any() or max()."
    )


def _argument_type_rewrite(error_message: str) -> str | None:
    match = next((m for pattern in _ILLEGAL_ARGUMENT_TYPE_RES if (m := pattern.search(error_message))), None)
    if match is None:
        return None
    types, function = match.group(1), match.group(2)
    return _type_mismatch_advice(f"`{function}` does not accept {types}.", types)


def _no_common_type_rewrite(error_message: str) -> str | None:
    match = _NO_COMMON_TYPE_RE.search(error_message)
    if match is None:
        return None
    types = match.group(1)
    return _type_mismatch_advice(
        f"ClickHouse has no common type for {types}, so it cannot compare or combine them.", types
    )


def _type_mismatch_advice(lead: str, types: str) -> str:
    if not _names_a_string_type(types):
        return f"{lead} Check the types with toTypeName(x) and convert one side to match the other."
    return (
        f"{lead} Event, person and session properties are strings in HogQL, so cast them before arithmetic, "
        "numeric comparison or date functions: toFloat(properties.x), toInt(properties.x) or "
        "toDateTime(properties.x), and compare a string property with a string literal."
    )


def _names_a_string_type(types: str) -> bool:
    """True when one of the mismatched types is a String, with or without Nullable or LowCardinality."""
    unwrapped = types
    while (stripped := _TYPE_WRAPPER_RE.sub(r"\1", unwrapped)) != unwrapped:
        unwrapped = stripped
    return any(part.strip() == "String" for part in re.split(r" and |, ", unwrapped))
