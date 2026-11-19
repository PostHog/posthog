"""Exported constants for actions."""

# jsonb_path_exists patterns that find a reference to one action in a stored query or filter. The `id` and `id_str`
# variables both carry the action id, because a stored reference can hold the id as a number or as a string. Callers
# put these patterns into SQL text, so they must stay constants.
ACTION_REFERENCE_JSONPATH = (
    '$.** ? ((@.kind == "ActionsNode" && (@.id == $id || @.id == $id_str))'
    " || (@.actionId == $id || @.actionId == $id_str)"
    ' || (@.type == "actions" && (@.id == $id || @.id == $id_str)))'
)
# The same match, for the legacy `actions` array of a filter.
ACTIONS_ARRAY_JSONPATH = "$.actions[*] ? (@.id == $id || @.id == $id_str)"
