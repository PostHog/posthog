from collections.abc import Iterable

from posthog.dataclasses import frozen


@frozen
class NodeIds:
    uuid: str
    generation_id: str | None
    span_id: str | None


class NodeIdResolver:
    """Resolves the ids SDKs send for a step (its event uuid, generation id or span id) to its event uuid."""

    def __init__(self, nodes: Iterable[NodeIds]) -> None:
        self._uuids: set[str] = set()
        self._aliases: dict[str, str] = {}
        for node in nodes:
            self._uuids.add(node.uuid)
            for alias in (node.generation_id, node.span_id):
                if alias and alias != node.uuid:
                    self._aliases.setdefault(alias, node.uuid)

    @property
    def aliases(self) -> dict[str, str]:
        """Each generation and span id that differs from its step's uuid, mapped to that uuid. The first step wins."""
        return dict(self._aliases)

    def resolve(self, node_id: str) -> str | None:
        if node_id in self._uuids:
            return node_id
        return self._aliases.get(node_id)
