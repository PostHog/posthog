"""Redshift function surface, derived subtractively from the Postgres surface.

Redshift is a fork of an old Postgres, so it shares most of Postgres's function surface. Rather
than re-listing everything, we start from the Postgres renames / handlers / passthrough sets and
remove the entries whose emitted SQL the Redshift engine would reject. Anything removed here is not
silently rewritten — it falls through to ``PostgresPrinter.visit_call``'s final branch and raises a
clear ``QueryError`` ("not supported in the Redshift dialect"), per the block-everything-incompatible
policy for direct Redshift sources.

Each removed name is annotated with why Redshift rejects it. Items marked ``UNCERTAIN`` are removed
conservatively and should be re-validated against a live Redshift cluster — if supported, delete them
from the removal set to let the inherited Postgres mapping through.
"""

from collections.abc import Callable

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


REDSHIFT_FUNCTION_RENAMES_LOWER: dict[str, str] = {
    name: target
    for name, target in POSTGRES_FUNCTION_RENAMES_LOWER.items()
    if name not in REDSHIFT_UNSUPPORTED_FUNCTIONS
}

REDSHIFT_FUNCTION_HANDLERS_LOWER: dict[str, Callable[[list[str]], str]] = {
    name: handler
    for name, handler in POSTGRES_FUNCTION_HANDLERS_LOWER.items()
    if name not in REDSHIFT_UNSUPPORTED_FUNCTIONS
}

REDSHIFT_PASSTHROUGH_FUNCTIONS: frozenset[str] = _without_unsupported(POSTGRES_PASSTHROUGH_FUNCTIONS)
