"""Typed columns for the `events_json_recent` exports that have filters or custom schema fields.

Most exports read `events_json_recent` as stored and need nothing here. Filters and custom schema fields are compiled
for the new events schema, so they read typed JSON columns, but `events_json_recent` stores those columns as text. For
those exports only, this converts the stored text back to the column types of `events_json`, at the cost of parsing
every row again.
"""

import re
import typing
from collections.abc import Collection, Sequence

from posthog.hogql.escape_sql import escape_clickhouse_identifier, escape_clickhouse_string

from posthog.clickhouse.events_json import (
    PERMANENT_SDK_DEBUG_PROPERTIES,
    TEMPORARY_EVENT_PROPERTY_ROOT_PREFIX,
    TEMPORARY_EVENT_PROPERTY_ROOTS,
    TEMPORARY_PROPERTIES_JSON_TYPE,
)
from posthog.models.event.sql import (
    EVENTS_JSON_ELEMENTS_COLUMNS,
    EVENTS_PROPERTIES_JSON_TYPE,
    PERSON_PROPERTIES_JSON_TYPE,
)

if typing.TYPE_CHECKING:
    from products.batch_exports.backend.service import BatchExportField

# The stored text of each document, kept beside the typed columns so the export still sends it as stored.
STORED_DOCUMENT_FIELD_EXPRESSIONS = {
    "properties": "_stored_properties",
    "person_properties": "_stored_person_properties",
}
STORED_TEMPORARY_PROPERTIES_COLUMN = "_stored_temporary_properties"
# Columns that are typed JSON in `events_json` but are text (or absent) in `events_json_recent`. Filters and custom
# fields printed for the new events schema read them with JSON subcolumn syntax, which fails on text.
_TYPED_COLUMN_REFERENCE = re.compile(r"\b(?:properties|person_properties|temporary_properties|elements_chain_\w+)\b")


def needs_typed_columns(
    fields: Sequence["BatchExportField"], filters: str, *, plain_expressions: Collection[str]
) -> bool:
    """Whether the filters or any field read typed columns. `plain_expressions` are the fields the query fills itself."""
    return bool(filters) or any(
        field["expression"] not in plain_expressions and _TYPED_COLUMN_REFERENCE.search(field["expression"]) is not None
        for field in fields
    )


def _parse_materialized_columns(columns_sql: str) -> list[str]:
    """`<expression> AS <name>` for each `, <name> <type> MATERIALIZED <expression>` line of a column list."""
    selected = []
    for line in columns_sql.strip().splitlines():
        name, definition = line.strip().removeprefix(",").strip().split(" ", 1)
        expression = definition.split(" MATERIALIZED ", 1)[1]
        selected.append(f"{expression} AS {name}")
    return selected


def _build_temporary_property_skip_clauses() -> str:
    """JSON type `SKIP` clauses for the paths that `is_temporary_event_property` puts in `temporary_properties`.

    RE2 has no lookahead, so the pattern for the `$sdk_debug_` prefix lists every way a root key can differ from the
    permanent key: it ends early, it has a different character, or it continues past the permanent key's name. A
    root key that equals the permanent key ends the path or is followed by a nested path's `.`. The pattern handles
    one permanent key, so the unpacking below fails at import when a second one is added.
    """
    (permanent_key,) = PERMANENT_SDK_DEBUG_PROPERTIES
    permanent_suffix = permanent_key.removeprefix(TEMPORARY_EVENT_PROPERTY_ROOT_PREFIX)
    differs_from_permanent = [
        f"{re.escape(permanent_suffix[:index])}(?:$|[^{re.escape(character)}])"
        for index, character in enumerate(permanent_suffix)
    ]
    differs_from_permanent.append(f"{re.escape(permanent_suffix)}[^.]")
    prefix_pattern = f"^{re.escape(TEMPORARY_EVENT_PROPERTY_ROOT_PREFIX)}(?:{'|'.join(differs_from_permanent)})"
    roots = (f"SKIP {escape_clickhouse_identifier(root)}" for root in sorted(TEMPORARY_EVENT_PROPERTY_ROOTS))
    return ", ".join([*roots, f"SKIP REGEXP {escape_clickhouse_string(prefix_pattern)}"])


_EVENTS_PROPERTIES_WITHOUT_TEMPORARY_JSON_TYPE = (
    f"{EVENTS_PROPERTIES_JSON_TYPE().removesuffix(')')}, {_build_temporary_property_skip_clauses()})"
)


def build_typed_events_json_recent_source(table: str) -> str:
    """`events_json_recent` with its document columns converted to the column types of `events_json`.

    The stored documents leave out the declared defaults that `events_json` reads back, and a declared path converts
    back to its default when it is absent, so filters and fields match what they match on `events_json`. The stored
    `properties` document also carries the temporary properties, which `events_json` keeps in `temporary_properties`
    only, so the conversion skips them there. The `elements_chain_*` columns are materialized in `events_json` only,
    so this computes them the same way.
    """
    elements_chain_columns = ",\n        ".join(_parse_materialized_columns(EVENTS_JSON_ELEMENTS_COLUMNS))
    return f"""(
    SELECT
        * REPLACE (
            CAST(properties, {escape_clickhouse_string(_EVENTS_PROPERTIES_WITHOUT_TEMPORARY_JSON_TYPE)}) AS properties,
            CAST(person_properties, '{PERSON_PROPERTIES_JSON_TYPE()}') AS person_properties,
            CAST(temporary_properties, '{TEMPORARY_PROPERTIES_JSON_TYPE}') AS temporary_properties
        ),
        {table}.properties AS {STORED_DOCUMENT_FIELD_EXPRESSIONS["properties"]},
        {table}.person_properties AS {STORED_DOCUMENT_FIELD_EXPRESSIONS["person_properties"]},
        {table}.temporary_properties AS {STORED_TEMPORARY_PROPERTIES_COLUMN},
        {elements_chain_columns}
    FROM {table}
    WHERE team_id = %(team_id)s::Int64
        AND inserted_at >= %(interval_start)s::DateTime64
        AND inserted_at < %(interval_end)s::DateTime64
)"""
