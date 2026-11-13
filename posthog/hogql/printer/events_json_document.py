"""The SQL that rebuilds the document an SDK sent from the columns of one events_json row.

The cleaner splits event properties at insert: each `$feature/<key>` value goes into the typed `$feature_flags` map,
`$active_feature_flags` is dropped, and the keys `is_temporary_event_property` names go into `temporary_properties`,
which ClickHouse clears 60 days after insertion. A whole-document read puts those parts back so the document matches
the legacy table while the parts exist. The cleaner also stores every object and array as a string of its JSON text,
and the builder puts each one back as the object or array. The JSON type cannot store `null`, so the cleaner drops
every top-level null field and records its key in the column's null-key array. This builder does not read those
arrays, so a property sent as `null` has no member in the rebuilt document. The HogQL printer and the batch export
source share this builder so every whole-document reader returns the same document.
"""

from collections.abc import Iterable

from posthog.hogql.constants import (
    FEATURE_FLAG_PROPERTY_PREFIX,
    FEATURE_FLAG_VARIANT_SENTINELS,
    INACTIVE_FEATURE_FLAG_VALUES,
)
from posthog.hogql.escape_sql import escape_clickhouse_string

from posthog.clickhouse.events_json import EVENTS_PROPERTIES_JSON_SUBCOLUMNS, PERSON_PROPERTIES_JSON_SUBCOLUMNS

_FEATURE_FLAGS_KEY = "$feature_flags"


def declared_string_paths(subcolumns: dict[str, str]) -> tuple[str, ...]:
    """The declared paths of a JSON column whose type is a plain or LowCardinality string."""
    return tuple(
        sorted(
            path for path, declared_type in subcolumns.items() if declared_type in ("String", "LowCardinality(String)")
        )
    )


EVENTS_PROPERTIES_DECLARED_STRING_PATHS = declared_string_paths(EVENTS_PROPERTIES_JSON_SUBCOLUMNS)
PERSON_PROPERTIES_DECLARED_STRING_PATHS = declared_string_paths(PERSON_PROPERTIES_JSON_SUBCOLUMNS)


def json_member_pairs_sql(
    document_sql: str,
    *,
    exclude_key: str | None = None,
    declared_string_paths: Iterable[str] = (),
) -> str:
    """`"key":<raw json>` strings for the members of a JSON column.

    The cleaner stores an object or array as a string of its JSON text, and nothing records which strings those are.
    A string that is a valid JSON object or array therefore goes into the document as that object or array, whether
    the cleaner stored it or the SDK sent that text.

    The JSON type materializes a declared string path on every row as `''`, so under those keys an empty value means
    the key was absent and the pair is left out. An empty string under any other key was sent and stays.
    """
    conditions = []
    string_paths = ", ".join(escape_clickhouse_string(path) for path in declared_string_paths)
    if string_paths:
        conditions.append(f"not (kv.2 = '\"\"' and kv.1 in ({string_paths}))")
    if exclude_key is not None:
        conditions.append(f"kv.1 != {escape_clickhouse_string(exclude_key)}")
    members = f"JSONExtractKeysAndValuesRaw(toJSONString({document_sql}))"
    if conditions:
        members = f"arrayFilter(kv -> {' and '.join(conditions)}, {members})"
    is_container = "(startsWith(kv.2, '\"[') or startsWith(kv.2, '\"{')) and isValidJSON(JSONExtractString(kv.2))"
    value = f"if({is_container}, JSONExtractString(kv.2), kv.2)"
    return f"arrayMap(kv -> concat(toJSONString(kv.1), ':', {value}), {members})"


def json_value_sql(path_sql: str) -> str:
    """The JSON of the value at an undeclared path of a JSON column, or NULL when the row has no such key.

    A string prints quoted and a number or a Bool as it is. A string that is a valid JSON object or array prints as
    that object or array, the way `json_member_pairs_sql` puts it into a document.
    """
    text = f"CAST({path_sql}, 'Nullable(String)')"
    is_container = f"(startsWith({text}, '[') or startsWith({text}, '{{')) and isValidJSON({text})"
    return f"if(isNull({path_sql}), NULL, if({is_container}, {text}, toJSONString({path_sql})))"


def stored_document_sql(document_sql: str, *, object_key: str | None = None) -> str:
    """Document text in the form the cleaner stores it, with every top-level object and array as a string.

    A reader that edits a rebuilt document, where those values are objects and arrays again, casts the result back
    into the JSON column through this. `object_key` names the one key the cleaner keeps as an object, the
    `$feature_flags` map of event properties.

    The cleaner (`parseNestedAsString` in clickhouse-udfs/util/cmd/json_clean_posthog_event_properties_udf/main.go)
    stores each value compact, with sorted keys, in the spelling `JSONExtractRaw` prints. A value rebuilt from a
    stored string is already sorted, and `JSONExtractKeysAndValuesRaw` prints it in that spelling and keeps its
    order, so the text written here is the text the cleaner would store. A value built any other way has to be
    sorted before it reaches this function.
    """
    is_container = "(startsWith(kv.2, '[') or startsWith(kv.2, '{'))"
    if object_key is not None:
        is_container = f"kv.1 != {escape_clickhouse_string(object_key)} and {is_container}"
    value = f"if({is_container}, toJSONString(kv.2), kv.2)"
    pairs = f"arrayMap(kv -> concat(toJSONString(kv.1), ':', {value}), JSONExtractKeysAndValuesRaw({document_sql}))"
    return f"concat('{{', arrayStringConcat({pairs}, ','), '}}')"


def feature_flag_pairs_sql(feature_flags_sql: str) -> str:
    """`"$feature/<key>":<value>` pairs plus the `"$active_feature_flags":[...]` pair, from a `$feature_flags` map.

    A boolean flag is stored as 'true' or 'false' and comes back as a JSON boolean. A variant comes back as a JSON
    string, with the cleaner sentinels mapped to the variant names. `$active_feature_flags` lists the flags not
    evaluated to off, in map order, and is present whenever the map has an entry. A flag sent as `null` is not in the
    map, so it has no pair.
    """
    variant_branches = ", ".join(
        f"value = {escape_clickhouse_string(sentinel)}, {escape_clickhouse_string(variant)}"
        for sentinel, variant in FEATURE_FLAG_VARIANT_SENTINELS.items()
    )
    flag_value = f"if(value in ('true', 'false'), value, toJSONString(multiIf({variant_branches}, value)))"
    prefix = escape_clickhouse_string(FEATURE_FLAG_PROPERTY_PREFIX)
    flag_pairs = (
        f"arrayMap((key, value) -> concat(toJSONString(concat({prefix}, key)), ':', {flag_value}), "
        f"mapKeys({feature_flags_sql}), mapValues({feature_flags_sql}))"
    )
    inactive_values = ", ".join(escape_clickhouse_string(value) for value in INACTIVE_FEATURE_FLAG_VALUES)
    active_flags = (
        f"toJSONString(mapKeys(mapFilter((key, value) -> value not in ({inactive_values}), {feature_flags_sql})))"
    )
    active_pair = f"if(empty({feature_flags_sql}), [], [concat('\"$active_feature_flags\":', {active_flags})])"
    return f"arrayConcat({flag_pairs}, {active_pair})"


def json_document_sql(document_sql: str, *, declared_string_paths: Iterable[str] = ()) -> str:
    """A JSON column as document text, built from its member pairs so declared defaults can be left out."""
    pairs = json_member_pairs_sql(document_sql, declared_string_paths=declared_string_paths)
    return f"concat('{{', arrayStringConcat({pairs}, ','), '}}')"


def person_document_sql(person_properties_sql: str) -> str:
    """The person properties column as document text, without the declared string defaults."""
    return json_document_sql(person_properties_sql, declared_string_paths=PERSON_PROPERTIES_DECLARED_STRING_PATHS)


def event_document_sql(
    properties_sql: str,
    temporary_properties_sql: str,
    feature_flags_sql: str | None,
) -> str:
    """The rebuilt document as JSON text. The caller wraps it in any restricted-key masking.

    `feature_flags_sql` is the flags map to rebuild from, already filtered of restricted flags, or None when every
    flag is hidden. The `$feature_flags` member of `properties` is left out because its entries come back as
    `$feature/<key>` pairs.
    """
    pairs = [
        json_member_pairs_sql(
            properties_sql,
            exclude_key=_FEATURE_FLAGS_KEY,
            declared_string_paths=EVENTS_PROPERTIES_DECLARED_STRING_PATHS,
        )
    ]
    if feature_flags_sql is not None:
        pairs.append(feature_flag_pairs_sql(feature_flags_sql))
    pairs.append(json_member_pairs_sql(temporary_properties_sql))
    return f"concat('{{', arrayStringConcat(arrayConcat({', '.join(pairs)}), ','), '}}')"
