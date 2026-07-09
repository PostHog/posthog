"""Redshift function surface, derived from the Postgres surface.

Redshift is a fork of an old Postgres, so it shares most of Postgres's function surface. Rather
than re-listing everything, we start from the Postgres renames / handlers / passthrough sets and
remove the entries whose emitted SQL the Redshift engine would reject. Anything removed here is not
silently rewritten — it falls through to ``PostgresPrinter.visit_call``'s final branch and raises a
clear ``QueryError`` ("not supported in the Redshift dialect"), per the block-everything-incompatible
policy for direct Redshift sources.

Each removed name is annotated with why Redshift rejects it. Items marked ``UNCERTAIN`` are removed
conservatively and should be re-validated against a live Redshift cluster — if supported, delete them
from the removal set to let the inherited Postgres mapping through.

On top of the subtraction, a small set of handlers rewrites functions whose Postgres rendering is
valid but means something different (or fails) on Redshift while a faithful equivalent exists —
these preserve HogQL semantics rather than blocking (see ``_REDSHIFT_ONLY_HANDLERS``).
"""

from collections.abc import Callable

from posthog.hogql.errors import QueryError
from posthog.hogql.printer.postgres_functions import (
    POSTGRES_FUNCTION_HANDLERS_LOWER,
    POSTGRES_FUNCTION_RENAMES_LOWER,
    POSTGRES_PASSTHROUGH_FUNCTIONS,
)

# Lowercased HogQL/ClickHouse function names whose Postgres rendering the Redshift engine rejects.
# Applied uniformly across renames, handlers, and passthrough.
REDSHIFT_UNSUPPORTED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # No array type in Redshift: ARRAY_AGG / UNNEST / ARRAY_TO_STRING don't exist.
        "grouparray",
        "grouparrayif",
        "arrayjoin",
        "arraystringconcat",
        # Redshift has json_extract_path_text (kept) but not json_extract_path (returns JSON).
        "jsonextractraw",
        "jsonextractarrayraw",
        # pg_typeof does not exist in Redshift.
        "totypename",
        # Redshift has no UUID type, so CAST(... AS UUID) fails.
        "touuid",
        # starts_with() is a Postgres builtin absent from Redshift.
        "startswith",
        # generate_series runs on the leader node only and fails in most query contexts.
        "generateseries",
        # TO_TIMESTAMP(epoch) is not supported (Redshift only has the format-string form).
        "fromunixtimestamp",
        # Aggregate FILTER (WHERE ...) clause is not supported by Redshift.
        "countif",
        "sumif",
        "avgif",
        "minif",
        "maxif",
        "anyif",
        "uniqif",
        "uniqexactif",
        # UNCERTAIN: EXTRACT(ISODOW/ISOYEAR FROM ...) — Redshift date_part lacks isodow/isoyear.
        "todayofweek",
        "toisoyear",
    }
)


def _without_unsupported(names: frozenset[str]) -> frozenset[str]:
    return frozenset(name for name in names if name not in REDSHIFT_UNSUPPORTED_FUNCTIONS)


def _handle_concat(args: list[str]) -> str:
    # Redshift's CONCAT is strictly two-argument and NULL-propagating; HogQL's concat is
    # variadic and treats NULL as ''. A coalesced `||` chain preserves both properties.
    if not args:
        return "''"
    coalesced = [f"COALESCE(CAST({arg} AS VARCHAR), '')" for arg in args]
    if len(coalesced) == 1:
        return coalesced[0]
    return f"({' || '.join(coalesced)})"


def _handle_position(args: list[str]) -> str:
    # Redshift only parses POSITION(needle IN haystack); the two-argument call form must be
    # STRPOS, which shares HogQL's (haystack, needle) argument order and 1-based result.
    if len(args) != 2:
        raise QueryError("position with a start offset is not supported in the Redshift dialect")
    return f"STRPOS({args[0]}, {args[1]})"


def _handle_avg(args: list[str]) -> str:
    # Redshift's avg over integer inputs returns a truncated integer; HogQL's avg is a float.
    return f"avg(CAST({args[0]} AS DOUBLE PRECISION))"


# Functions whose inherited Postgres rendering Redshift would reject or silently reinterpret;
# rewritten to a Redshift-native equivalent that keeps HogQL semantics.
_REDSHIFT_ONLY_HANDLERS: dict[str, Callable[[list[str]], str]] = {
    "concat": _handle_concat,
    "position": _handle_position,
    "avg": _handle_avg,
}

REDSHIFT_FUNCTION_RENAMES_LOWER: dict[str, str] = {
    name: target
    for name, target in POSTGRES_FUNCTION_RENAMES_LOWER.items()
    if name not in REDSHIFT_UNSUPPORTED_FUNCTIONS
}

# visit_call dispatches handlers before renames and passthrough, so the Redshift-only handlers
# shadow any inherited Postgres mapping for the same name.
REDSHIFT_FUNCTION_HANDLERS_LOWER: dict[str, Callable[[list[str]], str]] = {
    **{
        name: handler
        for name, handler in POSTGRES_FUNCTION_HANDLERS_LOWER.items()
        if name not in REDSHIFT_UNSUPPORTED_FUNCTIONS
    },
    **_REDSHIFT_ONLY_HANDLERS,
}

REDSHIFT_PASSTHROUGH_FUNCTIONS: frozenset[str] = _without_unsupported(POSTGRES_PASSTHROUGH_FUNCTIONS)
