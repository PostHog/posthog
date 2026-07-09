"""Publish-time access gate for public sharing.

Shared links execute without warehouse access control (the publish act is the access
decision - see SharedLinkUser), so the gate moves to the moment of publishing: the member
enabling a share must have access to every table its queries read. Otherwise sharing would
be an escalation channel - save a query over a restricted table, publish, read it through
the public link.
"""

from typing import TYPE_CHECKING, Any

from posthog.hogql.database.database import Database
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.metadata import get_table_names
from posthog.hogql.parser import parse_select

from products.notebooks.backend.facade.content import extract_inline_query_nodes
from products.product_analytics.backend.models.insight import Insight

if TYPE_CHECKING:
    from posthog.models import Team, User
    from posthog.models.sharing_configuration import SharingConfiguration

# Structured insight queries reference warehouse data via these nodes rather than by table name.
_DATA_WAREHOUSE_NODE_KINDS = frozenset({"DataWarehouseNode", "FunnelsDataWarehouseNode", "LifecycleDataWarehouseNode"})


def tables_blocked_for_publisher(user: "User", team: "Team", config: "SharingConfiguration") -> list[str]:
    """Tables the publisher can't access among everything the shared artifact queries.

    Resolution reuses the publisher's own HogQL schema build (`Database.create_for`), so it
    covers warehouse tables/views and access-controlled system tables uniformly, and follows
    the same feature gating as query execution. Empty list = safe to publish.
    """
    queries = _queries_exposed_by(config)
    if not queries:
        return []

    referenced: set[str] = set()
    for query in queries:
        referenced |= _referenced_table_names(query)
    if not referenced:
        return []

    database = Database.create_for(team=team, user=user)
    return sorted(referenced & set(database._denied_tables))


def _queries_exposed_by(config: "SharingConfiguration") -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    insight_ids = config.get_connected_insight_ids()
    if insight_ids:
        queries.extend(
            q
            for q in Insight.objects.filter(team_id=config.team_id, id__in=insight_ids).values_list("query", flat=True)
            if isinstance(q, dict)
        )
    if config.notebook:
        queries.extend(query for _node_id, query in extract_inline_query_nodes(config.notebook.content))
    return queries


def _referenced_table_names(value: Any) -> set[str]:
    """Table names a query dict references: HogQL sources by parsed name, structured insight
    queries via their data-warehouse nodes. An unparseable HogQL query contributes nothing -
    it errors for everyone at view time, which is not an access problem for this gate."""
    names: set[str] = set()
    if isinstance(value, dict):
        kind = value.get("kind")
        if kind == "HogQLQuery" and isinstance(value.get("query"), str):
            try:
                names |= set(get_table_names(parse_select(value["query"])))
            except BaseHogQLError:
                return names
        elif kind in _DATA_WAREHOUSE_NODE_KINDS and isinstance(value.get("table_name"), str):
            names.add(value["table_name"])
        for child in value.values():
            names |= _referenced_table_names(child)
    elif isinstance(value, list):
        for item in value:
            names |= _referenced_table_names(item)
    return names
