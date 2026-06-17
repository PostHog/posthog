from typing import Optional


def queried_access_controlled_resources(query) -> Optional[set[str]]:
    """The set of access-control scope names a query reads, e.g. "notebook", "survey";
    Empty when the query reads no access-controlled table.
    None when the query is malformed or unparseable."""

    # Deferred to break the query_runner -> this module -> hogql import cycle.
    from posthog.hogql.database.schema.system import access_controlled_system_tables  # noqa: PLC0415
    from posthog.hogql.errors import BaseHogQLError  # noqa: PLC0415
    from posthog.hogql.metadata import get_table_names  # noqa: PLC0415
    from posthog.hogql.parser import parse_select  # noqa: PLC0415

    # Raw HogQL is the only query that can reference system.* tables today
    if getattr(query, "kind", None) == "HogQLQuery":
        sql = getattr(query, "query", None)
        if not isinstance(sql, str):
            return None
        try:
            select = parse_select(sql)
        except BaseHogQLError:
            return None  # unparseable -> fail closed
        scopes = {f"system.{name}": scope for name, scope in access_controlled_system_tables().items()}
        return {scopes[name] for name in get_table_names(select) if name in scopes}

    # TODO: add warehouse_table / warehouse_view scopes here once warehouse access control is enforced

    return set()
