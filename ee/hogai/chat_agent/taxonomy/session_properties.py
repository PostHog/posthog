from posthog.hogql.database.schema.sessions_v2 import get_lazy_session_table_properties_v2

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP


def session_property_types() -> dict[str, str]:
    """
    Map each session property to the type to report for it, in the taxonomy's own order.

    A session entry property is copied from the event property it comes from, and most of those
    carry no type, so the copy has none either. The `sessions` table declares a column for each
    one, so the column's type answers for the copy. A property with no type is dropped from the
    taxonomy read, which is what left the web analytics acquisition fields, such as
    `$entry_utm_source`, impossible to verify before a query used them.

    A type in the taxonomy definition wins, because it is the type the rest of the product
    already shows for that property.
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
