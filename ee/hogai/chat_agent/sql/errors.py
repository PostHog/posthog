"""Turn a HogQL validation exception into the message a SQL-writing caller acts on."""

import re

from posthog.hogql.errors import BaseHogQLError

# Both the antlr-based cpp parser and the hand-rolled rust-py parser produce terse low-level wording
# on syntax failures. Any message opening with one of these reads as parser internals on its own.
_SYNTAX_ERROR_PREFIXES = (
    "no viable alternative",
    "trailing tokens after expression",
    "unexpected token in expression",
    "mismatched input",
)

# A parser message plus the fragment it points at is enough to locate the bad construct without
# echoing the whole query back, which for a long query buries the one part that needs rewriting.
_MAX_SYNTAX_DETAIL_CHARS = 200
_MAX_SYNTAX_FRAGMENT_CHARS = 60

_AMBIGUOUS_FIELD_PATTERN = re.compile(r"^Ambiguous query\. Found multiple sources for field: (\S+) \(")
# Characters of query text on each side of an ambiguous field. Enough to show the clause it sits in.
_AMBIGUOUS_CONTEXT_CHARS = 40


def hogql_validation_message(err: BaseHogQLError, query: str) -> str:
    """Build the validation message for a HogQL error, naming the construct a syntax failure hit.

    A friendly lead sentence replaces the terse parser wording, but the detail and the offending
    fragment follow it. Without them the caller cannot tell which construct was rejected, so it
    retries the same query instead of rewriting the one bad part.
    """
    message = str(err)
    if ambiguous_field := _AMBIGUOUS_FIELD_PATTERN.match(message):
        return _locate_ambiguous_field(message, ambiguous_field.group(1), err, query)
    if not message.startswith(_SYNTAX_ERROR_PREFIXES):
        return message

    clipped = _clip(message, _MAX_SYNTAX_DETAIL_CHARS).rstrip(".")
    described = f"HogQL parsing error: this query isn't valid HogQL. Parser detail: {clipped}."
    if err.start is None or err.end is None or not 0 <= err.start < err.end <= len(query):
        return described
    fragment = _clip(query[err.start : err.end].strip(), _MAX_SYNTAX_FRAGMENT_CHARS)
    return f"{described} The query failed at character {err.start}, near: {fragment}" if fragment else described


def _locate_ambiguous_field(message: str, field_name: str, err: BaseHogQLError, query: str) -> str:
    """Point at the unqualified reference, because a long query can use the same name in many clauses.

    The error position can come from the text of a view or a lazy table instead of this query.
    Only a position that holds the field name in this query is reported.
    """
    if err.start is None or err.end is None or not 0 <= err.start < err.end <= len(query):
        return message
    if query[err.start : err.end].strip() != field_name:
        return message
    before = query[max(0, err.start - _AMBIGUOUS_CONTEXT_CHARS) : err.start]
    after = query[err.end : err.end + _AMBIGUOUS_CONTEXT_CHARS]
    context = " ".join(f"{before}>>{field_name}<<{after}".split())
    return f"{message} The unqualified reference is at character {err.start}: {context}"


def _clip(text: str, limit: int) -> str:
    return f"{text[:limit]}…" if len(text) > limit else text
