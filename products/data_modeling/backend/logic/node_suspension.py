"""Suspension state for DAG nodes — the materialization circuit breaker.

A suspended node is skipped by every scheduled DAG run, so it can never produce the successful
materialization that would clear it. Every path here exists to give a node a way back.
"""

import hashlib
import datetime as dt
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from django.db import transaction

from products.data_modeling.backend.models.node import Node

if TYPE_CHECKING:
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

SUSPENDED_KEY = "suspended"
RESET_KEY = "suspension_reset"


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _system(node: Node) -> dict:
    return (node.properties or {}).get("system") or {}


def query_fingerprint(query: dict | None) -> str | None:
    """Recorded when a node suspends, so re-syncing an unchanged query (backfills, resync commands,
    managed-viewset sync) doesn't read as an edit and silently resume everything."""
    sql = (query or {}).get("query")
    if not isinstance(sql, str):
        return None
    return hashlib.sha256(sql.strip().encode()).hexdigest()[:16]


def suspension_state(node: Node) -> dict[str, dict]:
    return dict(_system(node).get(SUSPENDED_KEY) or {})


def is_node_suspended(node: Node, engine: str) -> bool:
    return bool(suspension_state(node).get(str(engine)))


def suspension_reset_at(node: Node, engine: str) -> str | None:
    """Failures before this point no longer count toward suspension."""
    return ((_system(node).get(RESET_KEY) or {}).get(str(engine)) or {}).get("at")


def mark_node_suspended(node: Node, *, engine: str, reason: str, job_id: str, fingerprint: str | None = None) -> None:
    properties: dict = node.properties or {}
    system = properties.setdefault("system", {})
    suspended = system.setdefault(SUSPENDED_KEY, {})
    suspended[str(engine)] = {
        "at": _now(),
        "reason": reason,
        "job_id": job_id,
        "query_fingerprint": fingerprint,
    }
    # A fresh suspension supersedes the resume that preceded it.
    (system.get(RESET_KEY) or {}).pop(str(engine), None)
    node.properties = properties


def clear_node_suspension(node: Node, *, engine: str | None = None, by: str = "materialization") -> bool:
    """Clears one engine, or all of them when engine is None.

    Stamps a watermark because the failures that caused the suspension are still the most recent
    jobs — without it the node re-suspends on its very next failure.
    """
    suspended = suspension_state(node)
    engines = [str(engine)] if engine is not None else list(suspended)
    cleared = [e for e in engines if suspended.get(e)]
    if not cleared:
        return False

    properties: dict = node.properties or {}
    system = properties.setdefault("system", {})
    resets = system.setdefault(RESET_KEY, {})
    at = _now()
    for e in cleared:
        del system[SUSPENDED_KEY][e]
        resets[e] = {"at": at, "by": by}
    node.properties = properties
    return True


def _persist_change(node: Node, change: Callable[[Node], bool]) -> bool:
    """Apply a change to the node's suspension state as a locked read-modify-write.

    `properties` is one JSON blob, so writing it from a caller's in-memory instance would drop
    anything a materialization committed to the same row since that instance was read. Every other
    writer of this field takes the row lock too (see the data-modeling Temporal activities).
    """
    with transaction.atomic():
        locked = Node.objects.select_for_update().filter(pk=node.pk, team_id=node.team_id).first()
        if locked is None or not change(locked):
            return False
        locked.save(update_fields=["properties"])
    node.properties = locked.properties
    return True


def resume_nodes(nodes: Iterable[Node], *, by: str, engine: str | None = None) -> int:
    """Returns how many of the nodes were actually suspended, not how many were passed in."""
    return sum(
        _persist_change(node, lambda locked: clear_node_suspension(locked, engine=engine, by=by)) for node in nodes
    )


def suspension_state_for_saved_query(saved_query: "DataWarehouseSavedQuery") -> dict[str, dict]:
    """Merged per-engine suspension state across every node backing the query.

    When duplicate DAGs give the query several nodes, the earliest suspension per engine wins —
    that is when the model actually stopped updating.
    """
    merged: dict[str, dict] = {}
    for node in Node.objects.filter(team_id=saved_query.team_id, saved_query_id=saved_query.id):
        for engine, entry in suspension_state(node).items():
            existing = merged.get(engine)
            if existing is None or (entry.get("at") or "") < (existing.get("at") or ""):
                merged[engine] = entry
    return merged


def resume_saved_query(saved_query: "DataWarehouseSavedQuery", *, by: str = "api") -> int:
    """One query can back several nodes when it landed in duplicate DAGs, and "resume this model"
    means all of them."""
    return resume_nodes(
        Node.objects.filter(team_id=saved_query.team_id, saved_query_id=saved_query.id),
        by=by,
    )


def clear_suspension_if_query_changed(node: Node, query: dict | None) -> bool:
    fingerprint = query_fingerprint(query)
    return _persist_change(node, lambda locked: _clear_stale_fingerprints(locked, fingerprint))


def _clear_stale_fingerprints(node: Node, fingerprint: str | None) -> bool:
    """A marker with no fingerprint predates fingerprinting; free it rather than strand it."""
    stale = [
        engine for engine, entry in suspension_state(node).items() if entry.get("query_fingerprint") != fingerprint
    ]
    cleared = False
    for engine in stale:
        cleared = clear_node_suspension(node, engine=engine, by="query_edit") or cleared
    return cleared
