from posthog.hogql.database.schema.sessions_v2 import get_lazy_session_table_properties_v2

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP


def session_property_types() -> dict[str, str]:
    """
    Map each session property to the type to report for it, in the taxonomy's own order.

    A session entry property is copied from an event property that carries no type, so the copy
    has none either, and an untyped property is dropped from the taxonomy read. The `sessions`
    table declares a column for each one, so its type answers for the copy.
    """
    column_types = {
        str(prop["name"]): str(prop["property_type"]) for prop in get_lazy_session_table_properties_v2(None)
    }
    types: dict[str, str] = {}
    for name, definition in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"].items():
        declared = definition.get("type")
        resolved = str(declared) if declared is not None else column_types.get(name)
        if resolved is not None:
            types[name] = resolved
    return types
