from copy import deepcopy
from typing import Any

from posthog.schema_migrations import LATEST_VERSIONS, MIGRATIONS, _discover_migrations


def upgrade(query: dict) -> dict:
    _discover_migrations()  # Lazy load migrations on first use
    return upgrade_node(query)


def upgrade_node(node: Any) -> Any:
    if isinstance(node, list):
        return [upgrade_node(item) for item in node]

    if isinstance(node, tuple):
        return tuple(upgrade_node(item) for item in node)

    if isinstance(node, dict):
        if "kind" in node and node["kind"] in LATEST_VERSIONS:
            while (version := (node.get("version") or 1)) < LATEST_VERSIONS[node["kind"]]:
                if version not in MIGRATIONS[node["kind"]]:
                    raise ValueError(f"Missing migration handler for {node['kind']} version {version}")
                node = MIGRATIONS[node["kind"]][version](deepcopy(node))

        for key, value in node.items():
            node[key] = upgrade_node(value)

        return node

    return node
