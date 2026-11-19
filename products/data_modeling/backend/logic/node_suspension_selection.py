import datetime as dt
from collections.abc import Iterator
from uuid import UUID

from posthog.dataclasses import frozen

from products.data_modeling.backend.logic.node_suspension import suspension_state
from products.data_modeling.backend.models.node import Node


@frozen
class Selection:
    engine: str | None
    reason_contains: tuple[str, ...]
    suspended_from: dt.datetime | None
    suspended_to: dt.datetime | None

    def matches(self, engine: str, entry: dict) -> bool:
        if self.engine is not None and engine != self.engine:
            return False
        reason = entry.get("reason") or ""
        if self.reason_contains and not any(fragment in reason for fragment in self.reason_contains):
            return False
        if self.suspended_from is None and self.suspended_to is None:
            return True
        try:
            at = dt.datetime.fromisoformat(entry.get("at") or "")
        except ValueError:
            return False  # a window was asked for, and a marker with no readable time is outside it
        if self.suspended_from is not None and at < self.suspended_from:
            return False
        return self.suspended_to is None or at < self.suspended_to


@frozen
class Marker:
    node: Node
    engine: str
    at: str
    reason: str

    def unchanged(self, node: Node) -> bool:
        """A model can re-suspend between the report and the write. A newer marker records a newer
        failure the operator never saw, so it stays."""
        return (suspension_state(node).get(self.engine) or {}).get("at") == self.at


def matching_suspension_markers(
    *,
    team_id: int | None,
    node_ids: list[UUID] | None,
    saved_query_ids: list[UUID] | None,
    selection: Selection,
) -> Iterator[Marker]:
    nodes = Node.objects.filter(properties__system__has_key="suspended")
    if team_id is not None:
        nodes = nodes.filter(team_id=team_id)
    if node_ids:
        nodes = nodes.filter(id__in=node_ids)
    if saved_query_ids:
        nodes = nodes.filter(saved_query_id__in=saved_query_ids)

    for node in nodes.order_by("team_id", "id").iterator():
        for engine, entry in suspension_state(node).items():
            if isinstance(entry, dict) and selection.matches(engine, entry):
                yield Marker(node=node, engine=engine, at=entry.get("at") or "", reason=entry.get("reason") or "")
