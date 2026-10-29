"""The SQL that rebuilds the document an SDK sent from the columns of one events_json row.

The cleaner splits event properties at insert: each `$feature/<key>` value goes into the typed `$feature_flags` map,
`$active_feature_flags` is dropped, and the keys `is_temporary_event_property` names go into `temporary_properties`,
which ClickHouse clears 60 days after insertion. The JSON type cannot store `null`, so the cleaner also drops every
null field and records its path in the column's null-key array. A whole-document read puts those parts back so the
document matches the legacy table while the parts exist. The HogQL printer and the batch export source share this
builder so every whole-document reader returns the same document.
"""

from collections.abc import Callable, Iterable

from posthog.hogql.constants import (
    FEATURE_FLAG_PROPERTY_PREFIX,
    FEATURE_FLAG_VARIANT_SENTINELS,
    INACTIVE_FEATURE_FLAG_VALUES,
)
from posthog.hogql.escape_sql import escape_clickhouse_string

from posthog.clickhouse.events_json import EVENTS_PROPERTIES_JSON_SUBCOLUMNS, PERSON_PROPERTIES_JSON_SUBCOLUMNS

_FEATURE_FLAGS_KEY = "$feature_flags"
# A null-key path joins object keys and array positions with `.` and writes a dot inside one key as `%2E`. The SQL
# spells that `%` as the escape `\x25`, because a printed query goes through %-style parameter substitution.
_ENCODED_DOT_SQL = "'\\x252E'"
_NO_PATHS_SQL = "CAST([], 'Array(Array(String))')"


def declared_array_paths(subcolumns: dict[str, str]) -> tuple[str, ...]:
    """The declared paths of a JSON column whose type is an array."""
    return tuple(sorted(path for path, declared_type in subcolumns.items() if declared_type.startswith("Array(")))


def declared_string_paths(subcolumns: dict[str, str]) -> tuple[str, ...]:
    """The declared paths of a JSON column whose type is a plain or LowCardinality string."""
    return tuple(
        sorted(
            path for path, declared_type in subcolumns.items() if declared_type in ("String", "LowCardinality(String)")
        )
    )


EVENTS_PROPERTIES_DECLARED_ARRAY_PATHS = declared_array_paths(EVENTS_PROPERTIES_JSON_SUBCOLUMNS)
EVENTS_PROPERTIES_DECLARED_STRING_PATHS = declared_string_paths(EVENTS_PROPERTIES_JSON_SUBCOLUMNS)
PERSON_PROPERTIES_DECLARED_STRING_PATHS = declared_string_paths(PERSON_PROPERTIES_JSON_SUBCOLUMNS)


def _decoded_key_sql(segment_sql: str) -> str:
    return f"replaceAll({segment_sql}, {_ENCODED_DOT_SQL}, '.')"


def _bind_sql(values: dict[str, str], body_sql: str) -> str:
    """`body_sql` with each name in `values` bound to its SQL value.

    ClickHouse has no local variables, so this maps a lambda over one-element arrays. A value used more than once
    is then printed and planned once.
    """
    names = ", ".join(values)
    arrays = ", ".join(f"[{value}]" for value in values.values())
    return f"arrayMap(({names}) -> {body_sql}, {arrays})[1]"


def _runs_sql(sorted_sql: str, key: Callable[[str], str], item: str) -> str:
    """The sorted array `sorted_sql` split into runs of items with the same `key`, which maps an item to SQL.

    ClickHouse copies an array that a lambda reads from outside its parameters once per element it maps, so
    grouping by filtering the whole array for each key costs the square of the null count. Sorting and splitting
    where the key changes stays near linear. `item` names the lambda parameters, which must not shadow an outer one.
    """
    before = f"{item}_before"
    items = f"{item}_sorted"
    split = (
        f"arraySplit(({item}, {before}) -> {key(item)} != {key(before)}, {items}, "
        f"arrayPopBack(arrayPushFront({items}, {items}[1])))"
    )
    return _bind_sql({items: sorted_sql}, split)


def _top_level_null_keys_sql(null_keys_sql: str) -> str:
    """The keys of the members sent as `null`, which are the recorded paths of one segment."""
    return f"arrayMap(null_key -> {_decoded_key_sql('null_key')}, arrayFilter(null_key -> position(null_key, '.') = 0, {null_keys_sql}))"


def _nested_null_paths_sql(null_keys_sql: str) -> str:
    """Each recorded path of more than one segment as its list of segments."""
    return (
        f"arrayMap(null_path -> arrayMap(null_segment -> {_decoded_key_sql('null_segment')}, splitByChar('.', null_path)), "
        f"arrayFilter(null_path -> position(null_path, '.') > 0, {null_keys_sql}))"
    )


def _restore_nulls_sql(value_sql: str, paths_sql: str) -> str:
    """Expand affected containers one level at a time, then join their JSON fragments.

    Each node carries (JSON text, remaining null paths). Finished fragments have no paths. Processing siblings
    together reads each container once per depth instead of rebuilding their common parent for every array.
    ClickHouse query limits apply normally; reconstruction never discards recorded nulls to meet a work budget.
    """
    is_array = "null_array"
    root_runs = _runs_sql("arraySort(null_node.2)", lambda path: f"{path}[1]", "null_tail")
    roots = (
        "arrayMap(null_root -> ("
        f"if({is_array}, if(toString(toInt64OrNull(null_root[1][1])) = null_root[1][1], "
        "toInt64OrZero(null_root[1][1]), toInt64(-1)), toInt64(0)), "
        f"if({is_array}, '', null_root[1][1]), 1, '', "
        f"arrayMap(null_path -> arrayPopFront(null_path), null_root)), {root_runs})"
    )
    members = (
        f"if({is_array}, "
        "arrayMap((null_element, null_index) -> (toInt64(null_index - 1), '', 0, null_element, "
        f"{_NO_PATHS_SQL}), JSONExtractArrayRaw(null_node.1), arrayEnumerate(JSONExtractArrayRaw(null_node.1))), "
        f"arrayMap(kv -> (toInt64(0), kv.1, 0, kv.2, {_NO_PATHS_SQL}), JSONExtractKeysAndValuesRaw(null_node.1)))"
    )
    runs = _runs_sql(
        f"arraySort(arrayConcat({members}, {roots}))", lambda entry: f"({entry}.1, {entry}.2)", "null_child"
    )
    runs = f"arrayFilter(null_run -> not {is_array} or null_run[1].3 = 0, {runs})"
    children = _bind_sql(
        {"null_children": runs},
        "arrayFlatten(arrayMap((null_run, null_index) -> ["
        "(concat(if(null_index = 1, '', ','), if(null_array, '', concat(toJSONString(null_run[1].2), ':'))), "
        f"{_NO_PATHS_SQL}), "
        "(null_run[1].4, null_run[-1].5)], null_children, arrayEnumerate(null_children)))",
    )
    expanded = (
        f"arrayConcat([(if({is_array}, '[', '{{'), {_NO_PATHS_SQL})], "
        f"{children}, [(if({is_array}, ']', '}}'), {_NO_PATHS_SQL})])"
    )
    expanded = _bind_sql({"null_array": "startsWith(null_node.1, '[')"}, expanded)
    node = (
        "multiIf(empty(null_node.2), [null_node], "
        f"empty(null_node.2[1]), [('null', {_NO_PATHS_SQL})], "
        "null_node.1 = '' or startsWith(null_node.1, '{') or startsWith(null_node.1, '['), "
        f"{expanded}, [(null_node.1, {_NO_PATHS_SQL})])"
    )
    return _bind_sql(
        {"null_paths": paths_sql},
        "arrayStringConcat(arrayFold((null_nodes, null_depth) -> "
        f"arrayFlatten(arrayMap(null_node -> {node}, null_nodes)), "
        f"range(arrayMax(arrayMap(null_path -> length(null_path), null_paths)) + 1), [({value_sql}, null_paths)]).1)",
    )


def json_member_pairs_sql(
    document_sql: str,
    null_keys_sql: str,
    *,
    exclude_key: str | None = None,
    declared_array_paths: Iterable[str] = (),
    declared_string_paths: Iterable[str] = (),
) -> str:
    """`"key":<raw json>` strings for the members of a JSON column, with the fields sent as `null` put back.

    The JSON type materializes a declared path on every row, as `[]` for an array and `''` for a string, so under
    those keys an empty value means the key was absent and the pair is left out. An empty array or string under any
    other key was sent and stays.

    A null-key path with one segment is a member sent as `null`. A longer path rebuilds the member it starts with,
    which is absent when every field below it was null.
    """
    conditions = []
    array_paths = ", ".join(escape_clickhouse_string(path) for path in declared_array_paths)
    if array_paths:
        conditions.append(f"not (kv.2 = '[]' and kv.1 in ({array_paths}))")
    string_paths = ", ".join(escape_clickhouse_string(path) for path in declared_string_paths)
    if string_paths:
        conditions.append(f"not (kv.2 = '\"\"' and kv.1 in ({string_paths}))")
    nested_paths = _nested_null_paths_sql(null_keys_sql)
    if exclude_key is not None:
        conditions.append(f"kv.1 != {escape_clickhouse_string(exclude_key)}")
        nested_paths = (
            f"arrayFilter(null_path -> null_path[1] != {escape_clickhouse_string(exclude_key)}, {nested_paths})"
        )
    members = f"JSONExtractKeysAndValuesRaw(toJSONString({document_sql}))"
    if conditions:
        members = f"arrayFilter(kv -> {' and '.join(conditions)}, {members})"

    member_pairs = f"arrayMap(kv -> concat(toJSONString(kv.1), ':', kv.2), {members})"

    # Each member and each root of a longer path becomes an entry (key, 0 for a member or 1 for a root, member
    # value, paths below the root). Sorted by key, a run holds a member, its root, or the member then its root.
    root_runs = _runs_sql(f"arraySort({nested_paths})", lambda path: f"{path}[1]", "null_path")
    entries = (
        "arraySort(arrayConcat("
        f"arrayMap(kv -> (kv.1, 0, kv.2, {_NO_PATHS_SQL}), {members}), "
        "arrayMap(null_root_run -> (null_root_run[1][1], 1, '', "
        f"arrayMap(null_path -> arrayPopFront(null_path), null_root_run)), {root_runs})))"
    )
    rebuilt_value = _restore_nulls_sql("null_key_run[1].3", "null_key_run[-1].4")
    rebuilt_pairs = (
        f"arrayMap(null_key_run -> concat(toJSONString(null_key_run[1].1), ':', {rebuilt_value}), "
        f"{_runs_sql(entries, lambda entry: f'{entry}.1', 'null_entry')})"
    )
    null_pairs = (
        f"arrayMap(null_key -> concat(toJSONString(null_key), ':null'), {_top_level_null_keys_sql(null_keys_sql)})"
    )
    # Most documents have no longer paths, so they keep their members as stored and skip the sort.
    return f"arrayConcat(if(empty({nested_paths}), {member_pairs}, {rebuilt_pairs}), {null_pairs})"


def feature_flag_pairs_sql(feature_flags_sql: str, null_keys_sql: str) -> str:
    """`"$feature/<key>":<value>` pairs plus the `"$active_feature_flags":[...]` pair, from a `$feature_flags` map.

    A boolean flag is stored as 'true' or 'false' and comes back as a JSON boolean. A variant comes back as a JSON
    string, with the cleaner sentinels mapped to the variant names. `$active_feature_flags` lists the flags not
    evaluated to off, in map order, and is present whenever the map has an entry. A flag sent as `null` is not in the
    map; the cleaner records it under the map's null-key path and it comes back as `null`.
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
    null_flag_pairs = (
        f"arrayMap(null_path -> concat(toJSONString(concat({prefix}, null_path[2])), ':null'), "
        f"arrayFilter(null_path -> length(null_path) = 2 and null_path[1] = {escape_clickhouse_string(_FEATURE_FLAGS_KEY)}, "
        f"{_nested_null_paths_sql(null_keys_sql)}))"
    )
    return f"arrayConcat({flag_pairs}, {active_pair}, {null_flag_pairs})"


def json_document_sql(
    document_sql: str,
    null_keys_sql: str,
    *,
    declared_array_paths: Iterable[str] = (),
    declared_string_paths: Iterable[str] = (),
) -> str:
    """A JSON column as document text, built from its member pairs so declared defaults can be left out."""
    pairs = json_member_pairs_sql(
        document_sql,
        null_keys_sql,
        declared_array_paths=declared_array_paths,
        declared_string_paths=declared_string_paths,
    )
    return f"concat('{{', arrayStringConcat({pairs}, ','), '}}')"


def person_document_sql(person_properties_sql: str, null_keys_sql: str) -> str:
    """The person properties column as document text, without the declared string defaults."""
    return json_document_sql(
        person_properties_sql, null_keys_sql, declared_string_paths=PERSON_PROPERTIES_DECLARED_STRING_PATHS
    )


def event_document_sql(
    properties_sql: str,
    properties_null_keys_sql: str,
    temporary_properties_sql: str,
    temporary_properties_null_keys_sql: str,
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
            properties_null_keys_sql,
            exclude_key=_FEATURE_FLAGS_KEY,
            declared_array_paths=EVENTS_PROPERTIES_DECLARED_ARRAY_PATHS,
            declared_string_paths=EVENTS_PROPERTIES_DECLARED_STRING_PATHS,
        )
    ]
    if feature_flags_sql is not None:
        pairs.append(feature_flag_pairs_sql(feature_flags_sql, properties_null_keys_sql))
    pairs.append(
        json_member_pairs_sql(
            temporary_properties_sql,
            temporary_properties_null_keys_sql,
        )
    )
    return f"concat('{{', arrayStringConcat(arrayConcat({', '.join(pairs)}), ','), '}}')"
