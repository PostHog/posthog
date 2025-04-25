from copy import deepcopy
from typing import Any
from posthog.schema_migrations import LATEST_VERSIONS, MIGRATIONS


def upgrade(query: dict) -> dict:
    return upgrade_node(query)


def upgrade_node(node: Any) -> Any:
    if isinstance(node, list):
        return [upgrade_node(item) for item in node]

    if isinstance(node, tuple):
        return tuple(upgrade_node(item) for item in node)

    if isinstance(node, dict):
        if "kind" in node and node["kind"] in LATEST_VERSIONS:
            while (v := (node.get("v") or 1)) < LATEST_VERSIONS[node["kind"]]:
                node = MIGRATIONS[node["kind"]][v](deepcopy(node))

        for key, value in list(node.items()):
            node[key] = upgrade_node(value)

        return node

    return node
