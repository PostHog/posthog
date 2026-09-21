"""Turn a known HogQL compatibility rejection into the rewrite that HogQL accepts.

HogQL is close enough to ClickHouse SQL that callers write plain ClickHouse and get a rejection
that states the rule but not the way out: ``greatest`` is binary here, ``LIKE`` takes no ``\\_``
escape, and ``CAST`` knows a short list of type names. The error names the construct, so the caller
knows which call failed, and then retries the same shape because nothing told it what HogQL accepts
instead. Each rule below adds the one accepted rewrite for a failure we see repeatedly.
"""

import re

# ClickHouse takes any number of arguments for these; HogQL caps both at 2 (see `mapping.py`), and
# nesting is exact rather than approximate because both are associative.
NESTABLE_BINARY_FUNCTIONS = ("greatest", "least")

# The type names `visit_type_cast` accepts, one per target type. Anything else — including every
# width-suffixed ClickHouse spelling such as `Float64` — is rejected.
ACCEPTED_CAST_TYPES = ("Int", "Float", "String", "Boolean", "Date", "DateTime")

# ClickHouse width and nullability decorations that carry no meaning for a HogQL cast.
_CAST_DECORATION_RE = re.compile(r"^(?:nullable|lowcardinality)\((.*)\)$|^u?([a-z]+?)\d*$")

_TOO_MANY_ARGS_RE = re.compile(r"Function '(\w+)' expects (\d+) arguments?, found (\d+)")
_BAD_ESCAPE_RE = re.compile(r"unrecognised escape '\\(.)'")
_BAD_CAST_RE = re.compile(r"Unsupported type cast to '([^']{1,40})'")


def _nested_call(name: str, arity: int) -> str:
    """Render the accepted nesting for an over-arity call, e.g. `greatest(a, greatest(b, c))`."""
    args = [chr(ord("a") + i) for i in range(arity)]
    call = args[-1]
    for arg in reversed(args[:-1]):
        call = f"{name}({arg}, {call})"
    return call


def suggest_cast_type(type_name: str) -> str | None:
    """Map a rejected ClickHouse cast type name onto the HogQL spelling, if one matches."""
    match = _CAST_DECORATION_RE.match(type_name.strip().lower())
    if match is None:
        return None
    inner, bare = match.groups()
    if inner is not None:
        return suggest_cast_type(inner)
    # Longest match first, so `datetime` resolves to DateTime rather than to its Date prefix.
    for accepted in sorted(ACCEPTED_CAST_TYPES, key=len, reverse=True):
        if accepted.lower().startswith(bare) or bare.startswith(accepted.lower()):
            return accepted
    return None


def build_compatibility_hint(error_message: str) -> str | None:
    """Build an additive hint naming the accepted rewrite, or None if no rule matches."""
    rewrites = [
        rewrite
        for rule in (_arity_rewrite, _escape_rewrite, _cast_rewrite)
        if (rewrite := rule(error_message)) is not None
    ]
    if not rewrites:
        return None
    return "\n".join(["<hogql_compatibility_hint>", *rewrites, "</hogql_compatibility_hint>"])


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
    accepted = ", ".join(ACCEPTED_CAST_TYPES)
    suggestion = suggest_cast_type(type_name)
    lead = (
        f"HogQL casts do not take width-suffixed ClickHouse type names such as `{type_name}`. "
        f"Accepted type names are: {accepted}."
    )
    return f"{lead} Use `CAST(x AS {suggestion})` or `to{suggestion}(x)`." if suggestion else lead
