"""Typed columns for the `events_json_recent` exports whose filters or fields read the new events schema.

Most exports read `events_json_recent` as stored and need nothing here. Filters and custom schema fields are compiled
for the new events schema, and the HTTP export rebuilds whole documents from the typed columns, so they read typed
JSON subcolumns such as ``events.properties.`$browser` ``. That syntax fails on `events_json_recent`, which stores the
documents as text. For the exports whose callers pass `reads_typed_columns`, `build_typed_events_json_recent_source`
wraps the table in a subquery that looks like `events_json`, at the cost of
parsing every row again. The subquery:

- casts `properties`, `person_properties` and `temporary_properties` to the JSON types of `events_json`, from
  `posthog/models/event/sql.py` and `posthog/clickhouse/events_json.py`.
- stores each top-level object or array as a string of its JSON text before the cast, as the cleaner of `events_json`
  does. HogQL reads a nested property by parsing its top-level member as text, which the stored documents keep as an
  object.
- keeps the stored text of each document in a `_stored_*` column, so the export still sends the document as stored.
- skips the temporary properties in the typed `properties`, following `is_temporary_event_property` in
  `posthog/clickhouse/events_json.py`. `events_json` keeps them in `temporary_properties` only.
- computes the `elements_chain_*` columns from the expressions that `events_json` materializes, in
  `EVENTS_JSON_ELEMENTS_COLUMNS`.

Each of these copies a rule that the `events_json` schema owns, so a change to that schema needs the matching change
here. The module is no longer needed if `events_json_recent` stores typed columns.
"""

import re

from posthog.hogql.escape_sql import escape_clickhouse_identifier, escape_clickhouse_string

from posthog.clickhouse.events_json import (
    EVENTS_JSON_RECENT_TABLE,
    EVENTS_PROPERTIES_JSON_SUBCOLUMNS,
    PERMANENT_SDK_DEBUG_PROPERTIES,
    PERSON_PROPERTIES_JSON_SUBCOLUMNS,
    TEMPORARY_EVENT_PROPERTY_ROOT_PREFIX,
    TEMPORARY_EVENT_PROPERTY_ROOTS,
    TEMPORARY_PROPERTIES_JSON_TYPE,
)
from posthog.models.event.sql import (
    EVENTS_JSON_ELEMENTS_COLUMNS,
    EVENTS_PROPERTIES_JSON_TYPE,
    PERSON_PROPERTIES_JSON_TYPE,
)

# The stored text of each document, kept beside the typed columns so the export still sends it as stored.
STORED_DOCUMENT_FIELD_EXPRESSIONS = {
    "properties": "_stored_properties",
    "person_properties": "_stored_person_properties",
}
STORED_TEMPORARY_PROPERTIES_COLUMN = "_stored_temporary_properties"


def _parse_materialized_columns(columns_sql: str) -> list[str]:
    """`<expression> AS <name>` for each `, <name> <type> MATERIALIZED <expression>` line of a column list.

    `events_json_recent` has no materialized `elements_chain_*` columns. Reading the expressions from the DDL of
    `events_json` keeps one definition of them, instead of a copy here that can drift.
    """
    selected = []
    for line in columns_sql.strip().splitlines():
        name, definition = line.strip().removeprefix(",").strip().split(" ", 1)
        expression = definition.split(" MATERIALIZED ", 1)[1]
        selected.append(f"{expression} AS {name}")
    return selected


def _build_temporary_property_skip_clauses() -> str:
    """JSON type `SKIP` clauses for the paths that `is_temporary_event_property` puts in `temporary_properties`.

    The stored `properties` text of `events_json_recent` includes keys such as `$set`, which `events_json` keeps in
    `temporary_properties` only. Without these clauses the typed `properties` would also hold them, and a read that
    rebuilds the whole document from both columns, such as the HTTP export's, would send `$set` twice.

    `is_temporary_event_property` marks every key in `TEMPORARY_EVENT_PROPERTY_ROOTS`, which becomes one `SKIP` each,
    and every key that starts with `$sdk_debug_` except `$sdk_debug_current_session_duration`. That second rule needs
    a `SKIP REGEXP`, and RE2 has no lookahead to say "but not this key". So the pattern lists every way a key can
    differ from the permanent key after the prefix: it ends early, it has a different character at some position, or
    it continues past the permanent key's name. For example, it matches `$sdk_debug_retry` and
    `$sdk_debug_current_session_durations`, and it does not match `$sdk_debug_current_session_duration` or a path
    nested under it.

    The pattern handles one permanent key, so the unpacking below fails at import when a second one is added.
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


def _stringify_container_members_sql(document_sql: str, declared_types: dict[str, str]) -> str:
    """`document_sql` with each top-level object or array member replaced by a string of its JSON text.

    A declared path that is not a string, such as the `$feature_flags` map, keeps its value, because the cast needs a
    value of the declared type there.
    """
    kept_paths = [
        path
        for path, declared_type in declared_types.items()
        if declared_type not in ("String", "LowCardinality(String)")
    ]
    is_kept = f"kv.1 in ({', '.join(escape_clickhouse_string(path) for path in kept_paths)}) or " if kept_paths else ""
    value = f"if({is_kept}JSONType(kv.2) not in ('Object', 'Array'), kv.2, toJSONString(kv.2))"
    members = f"arrayMap(kv -> concat(toJSONString(kv.1), ':', {value}), JSONExtractKeysAndValuesRaw({document_sql}))"
    return f"concat('{{', arrayStringConcat({members}, ','), '}}')"


_EVENTS_PROPERTIES_WITHOUT_TEMPORARY_JSON_TYPE = (
    f"{EVENTS_PROPERTIES_JSON_TYPE().removesuffix(')')}, {_build_temporary_property_skip_clauses()})"
)


def build_typed_events_json_recent_source() -> str:
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
            CAST(
                {_stringify_container_members_sql("properties", EVENTS_PROPERTIES_JSON_SUBCOLUMNS)},
                {escape_clickhouse_string(_EVENTS_PROPERTIES_WITHOUT_TEMPORARY_JSON_TYPE)}
            ) AS properties,
            CAST(
                {_stringify_container_members_sql("person_properties", PERSON_PROPERTIES_JSON_SUBCOLUMNS)},
                '{PERSON_PROPERTIES_JSON_TYPE()}'
            ) AS person_properties,
            CAST(
                {_stringify_container_members_sql("temporary_properties", {})}, '{TEMPORARY_PROPERTIES_JSON_TYPE}'
            ) AS temporary_properties
        ),
        {EVENTS_JSON_RECENT_TABLE}.properties AS {STORED_DOCUMENT_FIELD_EXPRESSIONS["properties"]},
        {EVENTS_JSON_RECENT_TABLE}.person_properties AS {STORED_DOCUMENT_FIELD_EXPRESSIONS["person_properties"]},
        {EVENTS_JSON_RECENT_TABLE}.temporary_properties AS {STORED_TEMPORARY_PROPERTIES_COLUMN},
        {elements_chain_columns}
    FROM {EVENTS_JSON_RECENT_TABLE}
    WHERE team_id = %(team_id)s::Int64
        AND inserted_at >= %(interval_start)s::DateTime64
        AND inserted_at < %(interval_end)s::DateTime64
)"""
