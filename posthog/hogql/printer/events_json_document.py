"""The SQL that rebuilds the document an SDK sent from the columns of one events_json row.

The cleaner splits event properties at insert: each `$feature/<key>` value goes into the typed `$feature_flags` map,
`$active_feature_flags` is dropped, and the keys `is_temporary_event_property` names go into `temporary_properties`,
which ClickHouse clears 60 days after insertion. The JSON type cannot store `null`, so the cleaner also drops every
null field and records its path in the column's null-key array. A whole-document read puts those parts back so the
document matches the legacy table while the parts exist. The HogQL printer and the batch export source share this
builder so every whole-document reader returns the same document.
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
# A null-key path joins object keys and array positions with `.` and writes a dot inside one key as `%2E`. The SQL
# spells that `%` as the escape `\x25`, because a printed query goes through %-style parameter substitution.
_ENCODED_DOT_SQL = "'\\x252E'"


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
    # How many of this path's parent objects the previous path also opened.
    shared = (
        "arrayFirstIndex(null_depth -> null_depth >= length(null_path) or null_depth >= length(null_previous) "
        "or null_path[null_depth] != null_previous[null_depth], range(1, length(null_path) + 1)) - 1"
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
    """
    is_array = f"startsWith({node_sql}, '[')"
    elements = f"if({is_array}, JSONExtractArrayRaw({node_sql}), [{node_sql}])"
    element_tails = (
        f"if({is_array}, arrayMap(null_position -> arrayMap(null_tail -> arrayPopFront(null_tail), "
        f"arrayFilter(null_tail -> null_tail[1] = toString(null_position - 1), {tails_sql})), "
        f"arrayEnumerate(JSONExtractArrayRaw({node_sql}))), [{tails_sql}])"
    )
    patched_elements = (
        f"arrayMap((null_element, null_element_tails) -> {_merge_nulls_sql('null_element', 'null_element_tails')}, "
        f"{elements}, {element_tails})"
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

    The child only gains null members, so a merge into an object member gives the child itself.
    """
    elements = f"JSONExtractArrayRaw({parent_sql})"
    replaced_elements = (
        f"arrayMap((null_element, null_position) -> if(null_position = {_array_position_sql(segment_sql)}, "
        f"{child_sql}, null_element), {elements}, arrayEnumerate({elements}))"
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


def _null_groups_sql(rest_paths_sql: str) -> str:
    """The paths below one member, grouped as (prefix, tails) at the last segment that can be an array position.

    Splitting there leaves tails that name object keys below their first segment, so one merge adds all of a
    group's nulls. Paths without such a segment share the empty prefix and are merged into the member at once.
    """
    split = "greatest(arrayLastIndex(null_segment -> match(null_segment, '^[0-9]+$'), arrayPopBack(null_rest)), 1)"
    pairs = (
        "arrayMap((null_rest, null_split) -> (arraySlice(null_rest, 1, null_split - 1), arraySlice(null_rest, null_split)), "
        f"{rest_paths_sql}, arrayMap(null_rest -> {split}, {rest_paths_sql}))"
    )
    return (
        "arrayMap(null_prefix -> (null_prefix, arrayMap(null_pair -> null_pair.2, "
        f"arrayFilter(null_pair -> null_pair.1 = null_prefix, {pairs}))), "
        f"arrayDistinct(arrayMap(null_pair -> null_pair.1, {pairs})))"
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

    roots = f"arrayDistinct(arrayMap(null_path -> null_path[1], {nested_paths}))"
    root_rests = (
        "arrayMap(null_root -> arrayMap(null_path -> arrayPopFront(null_path), "
        f"arrayFilter(null_path -> null_path[1] = null_root, {nested_paths})), {roots})"
    )
    root_value = (
        f"arrayFold((null_value, null_group) -> {_apply_null_group_sql('null_value', 'null_group.1', 'null_group.2')}, "
        f"{_null_groups_sql('null_rests')}, arrayFirst(kv -> kv.1 = null_root, {members}).2)"
    )
    kept_pairs = (
        f"arrayMap(kv -> concat(toJSONString(kv.1), ':', kv.2), arrayFilter(kv -> not has({roots}, kv.1), {members}))"
    )
    rebuilt_pairs = f"arrayMap((null_root, null_rests) -> concat(toJSONString(null_root), ':', {root_value}), {roots}, {root_rests})"
    null_pairs = (
        f"arrayMap(null_key -> concat(toJSONString(null_key), ':null'), {_top_level_null_keys_sql(null_keys_sql)})"
    )
    return f"arrayConcat({kept_pairs}, {rebuilt_pairs}, {null_pairs})"


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
    pairs.append(json_member_pairs_sql(temporary_properties_sql, temporary_properties_null_keys_sql))
    return f"concat('{{', arrayStringConcat(arrayConcat({', '.join(pairs)}), ','), '}}')"
