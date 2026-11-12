"""Which insight alerts a live workflow starts on.

Workflows reads its own triggers and imports this product, so it registers the lookup when Django
starts, rather than this product importing it. With no lookup registered, no workflow listens.
"""

from collections.abc import Callable

WorkflowTriggerLookup = Callable[[int], frozenset[str]]

_lookup: WorkflowTriggerLookup | None = None


def register(lookup: WorkflowTriggerLookup) -> None:
    global _lookup
    _lookup = lookup


def workflow_triggered_alert_ids(team_id: int) -> frozenset[str]:
    return _lookup(team_id) if _lookup is not None else frozenset()
