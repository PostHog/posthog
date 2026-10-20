"""Declared data dependencies and the nightly check that detects drift.

A canvas declares the events, properties, and tables it reads in ``capabilities.posthog.data``.
Agent-written software breaks quietly when a schema moves, so the check compares the declaration
of every live canvas against what the project has now and records what is missing. Repair stays
human-initiated: the result feeds a notice and the ``request_fix`` endpoint, never an automatic run.
"""

from typing import Any
from uuid import UUID

from django.db.models import F
from django.utils import timezone

import structlog

from products.canvas.backend.models import Canvas, CanvasDataCheck
from products.event_definitions.backend.facade.api import existing_event_names, existing_property_names
from products.warehouse_sources.backend.facade.api import all_queryable_table_keys

logger = structlog.get_logger(__name__)

DATA_SECTIONS = ("events", "properties", "tables")
PROPERTY_TYPES = ("event", "person", "group", "session")
MAX_DATA_ITEMS = 100


class CanvasDataChecksFailed(Exception):
    """Some canvases could not be checked. The run checked the others first."""


def empty_missing() -> dict[str, list[Any]]:
    return {"events": [], "properties": [], "tables": []}


def declared_data(capabilities: dict[str, Any] | None) -> dict[str, list[Any]]:
    data = ((capabilities or {}).get("posthog") or {}).get("data") or {}
    return {
        "events": [name for name in data.get("events") or [] if isinstance(name, str)],
        "properties": [
            entry
            for entry in data.get("properties") or []
            if isinstance(entry, dict) and isinstance(entry.get("name"), str) and isinstance(entry.get("type"), str)
        ],
        "tables": [name for name in data.get("tables") or [] if isinstance(name, str)],
    }


def declares_data(capabilities: dict[str, Any] | None) -> bool:
    return any(declared_data(capabilities).values())


def missing_data(team_id: int, capabilities: dict[str, Any] | None) -> dict[str, list[Any]]:
    """What the project no longer has of the canvas's declared data, in declaration order."""
    declared = declared_data(capabilities)
    present_events = existing_event_names(team_id, declared["events"])
    present_properties: set[tuple[str, str]] = set()
    for property_type in {entry["type"] for entry in declared["properties"]}:
        names = [entry["name"] for entry in declared["properties"] if entry["type"] == property_type]
        present_properties |= {(name, property_type) for name in existing_property_names(team_id, names, property_type)}
    present_tables = _present_table_names(team_id) if declared["tables"] else set()
    return {
        "events": [name for name in declared["events"] if name not in present_events],
        "properties": [
            {"name": entry["name"], "type": entry["type"]}
            for entry in declared["properties"]
            if (entry["name"], entry["type"]) not in present_properties
        ],
        "tables": [name for name in declared["tables"] if name not in present_tables],
    }


def _present_table_names(team_id: int) -> set[str]:
    # A query names a source table by its dotted key, e.g. "googleanalytics.devices". Accept the
    # stored row name too, so an older declaration that used it does not show as drift.
    names: set[str] = set()
    for table in all_queryable_table_keys(team_id).values():
        names.add(table.queryable_key)
        names.add(table.row_name)
    return names


def check_canvas_data(canvas: Canvas) -> CanvasDataCheck:
    """Check one canvas's live version and rewrite its data check row."""
    version = canvas.current_source_version
    missing = missing_data(canvas.team_id, version.capabilities if version else None)
    status = CanvasDataCheck.STATUS_DRIFT if any(missing.values()) else CanvasDataCheck.STATUS_OK
    check, _ = CanvasDataCheck.objects.for_team(canvas.team_id).update_or_create(
        canvas=canvas,
        defaults={
            "team_id": canvas.team_id,
            "source_version": version,
            "status": status,
            "missing": missing,
            "checked_at": timezone.now(),
        },
    )
    return check


def run_data_dependency_checks() -> dict[str, int]:
    """Check every live canvas whose head version declares data. Returns counts for the task log."""
    canvases = (
        Canvas.objects.unscoped()
        .filter(deleted=False, current_source_version__capabilities__posthog__data__isnull=False)
        .select_related("current_source_version")
        .order_by("team_id", "id")
    )
    checked = drifted = 0
    failed: list[str] = []
    for canvas in canvases.iterator(chunk_size=200):
        if not declares_data(canvas.current_source_version.capabilities if canvas.current_source_version else None):
            continue
        try:
            check = check_canvas_data(canvas)
        except Exception:
            # Check the other canvases first, then fail the run so the failure is visible.
            logger.exception("canvas_data_check_failed", canvas_id=str(canvas.id), team_id=canvas.team_id)
            failed.append(str(canvas.id))
            continue
        checked += 1
        if check.status == CanvasDataCheck.STATUS_DRIFT:
            drifted += 1
    if failed:
        raise CanvasDataChecksFailed(
            f"{len(failed)} canvas data checks failed ({checked} checked, {drifted} drifted): {', '.join(failed[:20])}"
        )
    return {"checked": checked, "drifted": drifted}


def _current_check(team_id: int, canvas_id: UUID | str) -> CanvasDataCheck | None:
    # A check of an older version says nothing about the live one: a publish can add, change, or
    # remove the data declaration. Only a check of the canvas's current version counts.
    return (
        CanvasDataCheck.objects.for_team(team_id)
        .filter(canvas_id=canvas_id, source_version_id=F("canvas__current_source_version_id"))
        .first()
    )


def data_check_record(team_id: int, canvas_id: UUID | str) -> dict[str, Any]:
    """The check of the canvas's live version, or the unchecked shape when that version has no check yet."""
    check = _current_check(team_id, canvas_id)
    if check is None:
        return {"status": "unchecked", "checked_at": None, "missing": empty_missing()}
    return {"status": check.status, "checked_at": check.checked_at, "missing": {**empty_missing(), **check.missing}}


def latest_missing_data(team_id: int, canvas_id: UUID | str) -> dict[str, Any] | None:
    check = _current_check(team_id, canvas_id)
    return check.missing if check is not None else None
