"""The SQL that rebuilds the document an SDK sent from the columns of one events_json row.

The cleaner splits event properties at insert: each `$feature/<key>` value goes into the typed `$feature_flags` map,
`$active_feature_flags` is dropped, and the keys `is_temporary_event_property` names go into `temporary_properties`,
which ClickHouse clears 60 days after insertion. A whole-document read puts those parts back so the document matches
the legacy table while the parts exist. The HogQL printer and the batch export source share this builder so every
whole-document reader returns the same document.
"""

from collections.abc import Iterable

from posthog.hogql.constants import (
    FEATURE_FLAG_PROPERTY_PREFIX,
    FEATURE_FLAG_VARIANT_SENTINELS,
    INACTIVE_FEATURE_FLAG_VALUES,
)
from posthog.hogql.escape_sql import escape_clickhouse_string

from posthog.clickhouse.events_json import EVENTS_PROPERTIES_JSON_SUBCOLUMNS


def declared_array_paths(subcolumns: dict[str, str]) -> tuple[str, ...]:
    """The declared paths of a JSON column whose type is an array."""
    return tuple(sorted(path for path, declared_type in subcolumns.items() if declared_type.startswith("Array(")))


EVENTS_PROPERTIES_DECLARED_ARRAY_PATHS = declared_array_paths(EVENTS_PROPERTIES_JSON_SUBCOLUMNS)


def json_member_pairs_sql(
    document_sql: str, *, exclude_key: str | None = None, declared_array_paths: Iterable[str] = ()
) -> str:
    """`"key":<raw json>` strings for the members of a JSON column.

    The JSON type materializes a declared array path as `[]` on every row, so for those paths an empty array means
    the key was absent and the pair is left out. An empty array under any other key was sent and stays.
    """
    conditions = []
    array_paths = ", ".join(escape_clickhouse_string(path) for path in declared_array_paths)
    if array_paths:
        conditions.append(f"not (kv.2 = '[]' and kv.1 in ({array_paths}))")
    if exclude_key is not None:
        conditions.append(f"kv.1 != {escape_clickhouse_string(exclude_key)}")
    members = f"JSONExtractKeysAndValuesRaw(toJSONString({document_sql}))"
    if conditions:
        members = f"arrayFilter(kv -> {' and '.join(conditions)}, {members})"
    return f"arrayMap(kv -> concat(toJSONString(kv.1), ':', kv.2), {members})"


def feature_flag_pairs_sql(feature_flags_sql: str) -> str:
    """`"$feature/<key>":<value>` pairs plus the `"$active_feature_flags":[...]` pair, from a `$feature_flags` map.

    A boolean flag is stored as 'true' or 'false' and comes back as a JSON boolean. A variant comes back as a JSON
    string, with the cleaner sentinels mapped to the variant names. `$active_feature_flags` lists the flags not
    evaluated to off, in map order, and is present whenever the map has an entry.
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


def event_document_sql(properties_sql: str, temporary_properties_sql: str, feature_flags_sql: str | None) -> str:
    """The rebuilt document as JSON text. The caller wraps it in the strip UDF and any restricted-key masking.

    `feature_flags_sql` is the flags map to rebuild from, already filtered of restricted flags, or None when every
    flag is hidden. The `$feature_flags` member of `properties` is left out because its entries come back as
    `$feature/<key>` pairs.
    """
    pairs = [
        json_member_pairs_sql(
            properties_sql, exclude_key="$feature_flags", declared_array_paths=EVENTS_PROPERTIES_DECLARED_ARRAY_PATHS
        )
    ]
    if feature_flags_sql is not None:
        pairs.append(feature_flag_pairs_sql(feature_flags_sql))
    pairs.append(json_member_pairs_sql(temporary_properties_sql))
    return f"concat('{{', arrayStringConcat(arrayConcat({', '.join(pairs)}), ','), '}}')"
