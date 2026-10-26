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
_NO_SEGMENTS_SQL = "CAST([], 'Array(String)')"
_MAX_NULL_REBUILD_BYTES = 16 * 1024 * 1024


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


def _null_skeleton_sql(paths_sql: str) -> str:
    """A JSON object that holds `null` at each path. Every segment of these paths is an object key.

    Sorting puts the paths below one object next to each other. Each path closes the objects of the previous path
    that it does not share, opens its own objects below the shared ones, and writes its leaf.
    """
    sorted_paths = f"arraySort({paths_sql})"
    previous_paths = f"arrayPushFront(arrayPopBack({sorted_paths}), [])"
    # How many of this path's parent objects the previous path also opened. The two paths go in as lambda
    # parameters, because a lambda that reads them from outside copies them once per segment.
    common_length = "least(length(null_path), length(null_previous))"
    first_difference = (
        "arrayFirstIndex((null_segment, null_previous_segment) -> null_segment != null_previous_segment, "
        f"arraySlice(null_path, 1, {common_length}), arraySlice(null_previous, 1, {common_length}))"
    )
    shared = (
        f"least(length(null_path), greatest(length(null_previous), 1), "
        f"ifNull(nullIf({first_difference}, 0), length(null_path))) - 1"
    )
    piece = (
        "concat(if(empty(null_previous), '', concat(repeat('}', length(null_previous) - 1 - null_shared), ',')), "
        "arrayStringConcat(arrayMap(null_key -> concat(toJSONString(null_key), ':{'), "
        "arraySlice(null_path, null_shared + 1, length(null_path) - 1 - null_shared))), "
        "toJSONString(null_path[-1]), ':null')"
    )
    return (
        f"concat('{{', arrayStringConcat(arrayMap((null_path, null_previous, null_shared) -> {piece}, "
        f"{sorted_paths}, {previous_paths}, arrayMap((null_path, null_previous) -> {shared}, {sorted_paths}, "
        f"{previous_paths}))), repeat('}}', length(arrayPopBack({sorted_paths}[-1]))), '}}')"
    )


def _merge_nulls_sql(value_sql: str, paths_sql: str) -> str:
    """The JSON text `value_sql` with `null` added at each object path below it.

    An absent value becomes a new object. A value that is not an object stays as it is: the cleaner records a path
    through a scalar only when the sent document repeated a key with values of different types.
    """
    return (
        f"if(empty({paths_sql}) or not ({value_sql} = '' or startsWith({value_sql}, '{{')), {value_sql}, "
        f"JSONMergePatch(if({value_sql} = '', '{{}}', {value_sql}), {_null_skeleton_sql(paths_sql)}))"
    )


def _array_position_sql(segment_sql: str) -> str:
    """The 1-based element a path segment names, or 0, which names no element, when the segment is not a position."""
    return f"ifNull(toInt64OrNull({segment_sql}) + 1, 0)"


def _patch_node_sql(node_sql: str, tails_sql: str) -> str:
    """The JSON text `node_sql` with `null` added at each tail path. Below an array, a tail starts with a position.

    An object node is handled as a list of one element, so each element of an array and an object node go
    through the same merge. Below an array, a tail that starts with a key is dropped. The cleaner records one when it
    wraps a sent object in an array, such as an `$exception_list` sent as one object, and merging it would replace
    the array.

    The elements and the tails are sorted together by position, so each element is followed by its own tails.
    """
    is_array = f"startsWith({node_sql}, '[')"
    elements = f"if({is_array}, JSONExtractArrayRaw({node_sql}), [{node_sql}])"
    # A position the cleaner wrote is a plain number. Any other first segment gets -1, which names no element.
    tail_position = "if(toString(toInt64OrNull(null_tail[1])) = null_tail[1], toInt64OrZero(null_tail[1]), toInt64(-1))"
    tail_entries = (
        f"if({is_array}, arrayMap(null_tail -> ({tail_position}, 1, '', arrayPopFront(null_tail)), {tails_sql}), "
        f"arrayMap(null_tail -> (toInt64(0), 1, '', null_tail), {tails_sql}))"
    )
    element_entries = (
        f"arrayMap((null_element, null_position) -> (toInt64(null_position) - 1, 0, null_element, {_NO_SEGMENTS_SQL}), "
        f"{elements}, arrayEnumerate({elements}))"
    )
    element_runs = _runs_sql(
        f"arraySort(arrayConcat({element_entries}, {tail_entries}))", lambda entry: f"{entry}.1", "null_entry"
    )
    patched_elements = (
        f"arrayMap(null_run -> {_merge_nulls_sql('null_run[1].3', 'arrayPopFront(null_run).4')}, "
        f"arrayFilter(null_run -> null_run[1].2 = 0, {element_runs}))"
    )
    return f"concat(if({is_array}, '[', ''), arrayStringConcat({patched_elements}, ','), if({is_array}, ']', ''))"


def _child_sql(value_sql: str, segment_sql: str) -> str:
    """The JSON text of the array element or object member that `segment_sql` names, or '' when there is none."""
    return (
        f"multiIf(startsWith({value_sql}, '['), JSONExtractRaw({value_sql}, {_array_position_sql(segment_sql)}), "
        f"startsWith({value_sql}, '{{'), JSONExtractRaw({value_sql}, {segment_sql}), '')"
    )


def _set_child_sql(parent_sql: str, segment_sql: str, child_sql: str) -> str:
    """`parent_sql` with the array element or object member that `segment_sql` names replaced by `child_sql`.

    The child only gains null members, so a merge into an object member gives the child itself. An array element is
    replaced by slicing, because a lambda that read the child would copy it once per element.
    """
    replaced_elements = _bind_sql(
        {"null_elements": f"JSONExtractArrayRaw({parent_sql})", "null_target": _array_position_sql(segment_sql)},
        "if(null_target between 1 and length(null_elements), arrayConcat(arraySlice(null_elements, 1, null_target - 1), "
        f"[{child_sql}], arraySlice(null_elements, null_target + 1)), null_elements)",
    )
    member = f"concat('{{', toJSONString({segment_sql}), ':', {child_sql}, '}}')"
    return (
        f"multiIf(startsWith({parent_sql}, '['), concat('[', arrayStringConcat({replaced_elements}, ','), ']'), "
        f"startsWith({parent_sql}, '{{'), JSONMergePatch({parent_sql}, {member}), {parent_sql} = '', {member}, "
        f"{parent_sql})"
    )


def _apply_null_group_sql(value_sql: str, prefix_sql: str, tails_sql: str) -> str:
    """`value_sql` with the nulls of one group added: descend along the prefix, patch that node, then rebuild upward.

    The descent records the JSON text at each step of the prefix. The fold walks those steps back from the node,
    so its first step patches the node and each later step sets the patched child into its parent.
    """
    steps = (
        "arrayFold((null_steps, null_step_segment) -> "
        f"arrayPushBack(null_steps, {_child_sql('null_steps[-1]', 'null_step_segment')}), {prefix_sql}, [{value_sql}])"
    )
    patch = _patch_node_sql("null_node", tails_sql)
    set_child = _set_child_sql("null_node", "null_node_segment", "null_patched")
    return (
        f"arrayFold((null_patched, null_node, null_node_segment, null_index) -> "
        f"if(null_index = 1, {patch}, {set_child}), arrayReverse({steps}), "
        f"arrayPushFront(arrayReverse({prefix_sql}), ''), range(1, length({prefix_sql}) + 2), '')"
    )


def _array_split_sql(rest_sql: str) -> str:
    """Where `_null_groups_sql` splits a path: its last segment that can be an array position, but not its leaf."""
    return f"greatest(arrayLastIndex(null_segment -> match(null_segment, '^[0-9]+$'), arrayPopBack({rest_sql})), 1)"


def _null_groups_sql(rest_paths_sql: str) -> str:
    """The paths below one member, grouped as (prefix, tails) at the last segment that can be an array position.

    Splitting there leaves tails that name object keys below their first segment, so one merge adds all of a
    group's nulls. Paths without such a segment share the empty prefix and are merged into the member at once.
    """
    split = _array_split_sql("null_rest")
    pairs = (
        "arraySort(arrayMap(null_rest -> "
        f"(arraySlice(null_rest, 1, {split} - 1), arraySlice(null_rest, {split})), {rest_paths_sql}))"
    )
    return (
        "arrayMap(null_pair_run -> (null_pair_run[1].1, null_pair_run.2), "
        f"{_runs_sql(pairs, lambda pair: f'{pair}.1', 'null_pair')})"
    )


def _restorable_null_keys_sql(null_keys_sql: str, document_sql: str) -> str:
    """The recorded null keys of `document_sql`, or none when putting them back would re-read too much JSON.

    A group with a prefix re-reads and rebuilds its member once for each segment from the member down to its array,
    so many arrays that hold nulls, or an array below many objects, multiply the cost of reading a large document.
    Each step reads at most the whole document. Over `_MAX_NULL_REBUILD_BYTES`, the document comes back without
    its nulls, the same as when the cleaner records none.
    """
    group_paths = (
        f"arrayMap(null_path -> arraySlice(null_path, 1, {_array_split_sql('arrayPopFront(null_path)')}), "
        f"{_nested_null_paths_sql(null_keys_sql)})"
    )
    steps = (
        "arraySum(arrayMap(null_group_path -> length(null_group_path), arrayDistinct("
        f"arrayFilter(null_group_path -> length(null_group_path) > 1, {group_paths}))))"
    )
    return f"if({steps} * length(toJSONString({document_sql})) > {_MAX_NULL_REBUILD_BYTES}, [], {null_keys_sql})"


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
    rebuilt_value = (
        f"arrayFold((null_value, null_group) -> {_apply_null_group_sql('null_value', 'null_group.1', 'null_group.2')}, "
        f"{_null_groups_sql('null_key_run[-1].4')}, null_key_run[1].3)"
    )
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
        _restorable_null_keys_sql(null_keys_sql, document_sql),
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
    properties_null_keys_sql = _restorable_null_keys_sql(properties_null_keys_sql, properties_sql)
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
            _restorable_null_keys_sql(temporary_properties_null_keys_sql, temporary_properties_sql),
        )
    )
    return f"concat('{{', arrayStringConcat(arrayConcat({', '.join(pairs)}), ','), '}}')"
