"""Suspension state for DAG nodes — the materialization circuit breaker.

Canonical home for the ``properties["system"]["suspended"]`` shape. The materialization
activities write it after repeated failures; the DAG sync, the node API and manual runs clear it.

A suspended node is skipped by every scheduled DAG run, so it can never produce the successful
materialization that would clear it. Every path here exists to give a node a way back.
"""

import hashlib
import datetime as dt
from collections.abc import Iterable

from products.data_modeling.backend.models.node import Node

SUSPENDED_KEY = "suspended"
RESET_KEY = "suspension_reset"


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _system(node: Node) -> dict:
    return (node.properties or {}).get("system") or {}


def query_fingerprint(query: dict | None) -> str | None:
    """Fingerprint of a saved query's SQL, recorded when a node suspends.

    Lets a later edit be recognized as a genuine change, so re-syncing an unchanged query
    (backfills, resync commands, managed-viewset sync) doesn't silently resume everything.
    """
    sql = (query or {}).get("query")
    if not isinstance(sql, str):
        return None
    return hashlib.sha256(sql.strip().encode()).hexdigest()[:16]


def suspension_state(node: Node) -> dict[str, dict]:
    return dict(_system(node).get(SUSPENDED_KEY) or {})


def is_node_suspended(node: Node, engine: str) -> bool:
    return bool(suspension_state(node).get(str(engine)))


def suspension_reset_at(node: Node, engine: str) -> str | None:
    """When this engine was last resumed. Failures before it no longer count toward suspension."""
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
    """Clear suspension for one engine (or all) and stamp when it happened.

    The watermark matters: the failures that caused the suspension are still the most recent jobs,
    so without it the node re-suspends on its very next failure instead of getting a fresh window.
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


def resume_nodes(nodes: Iterable[Node], *, by: str, engine: str | None = None) -> int:
    """Resume suspended nodes, returning how many were actually suspended."""
    resumed = 0
    for node in nodes:
        if clear_node_suspension(node, engine=engine, by=by):
            node.save(update_fields=["properties"])
            resumed += 1
    return resumed


def clear_suspension_if_query_changed(node: Node, query: dict | None) -> bool:
    """Resume a node whose query no longer matches the one that got it suspended.

    Fixing the SQL is the most common remedy, and on the scheduled path it is the only one the
    user can reach — a suspended node is never executed, so it can never succeed its way out.
    A marker with no fingerprint predates fingerprinting; free it rather than strand it.
    """
    fingerprint = query_fingerprint(query)
    stale = [
        engine for engine, entry in suspension_state(node).items() if entry.get("query_fingerprint") != fingerprint
    ]
    cleared = False
    for engine in stale:
        cleared = clear_node_suspension(node, engine=engine, by="query_edit") or cleared
    return cleared
