"""The endpoint version whose materialization a node's saved query backs.

Endpoints depends on data modeling, not the reverse, so nothing here can reach EndpointVersion.
The endpoints enable path stamps the link onto the node and the node serializer reads it back.
"""

from typing import Any
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen

from products.data_modeling.backend.models.node import Node

ENDPOINT_PROPERTY = "endpoint"


@frozen
class EndpointLink:
    name: str
    version: int


def link_endpoint_nodes(*, team_id: int, saved_query_id: UUID, endpoint_name: str, version: int) -> int:
    """Stamp every node of the saved query with the endpoint version it materializes. Returns the count.

    `properties` is one JSON blob, so this takes the row lock every other writer of the field takes —
    without it the stamp would drop suspension state a concurrent materialization committed to the
    same row after this read.
    """
    with transaction.atomic():
        nodes = list(Node.objects.select_for_update().filter(team_id=team_id, saved_query_id=saved_query_id))
        for node in nodes:
            properties = node.properties or {}
            properties[ENDPOINT_PROPERTY] = {"name": endpoint_name, "version": version}
            node.properties = properties
            node.save(update_fields=["properties"])
    return len(nodes)


def endpoint_link(properties: dict[str, Any] | None) -> EndpointLink | None:
    """`properties` is an unvalidated JSON blob, so a malformed stamp reads as "not an endpoint"
    rather than failing the node serializer and with it the whole list response."""
    link = (properties or {}).get(ENDPOINT_PROPERTY)
    if not isinstance(link, dict):
        return None
    name, version = link.get("name"), link.get("version")
    if not isinstance(name, str) or not isinstance(version, int) or isinstance(version, bool):
        return None
    return EndpointLink(name=name, version=version)
