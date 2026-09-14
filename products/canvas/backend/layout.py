"""Grid canvas layout validation and patch operations.

A grid canvas's "source" is a layout document — a grid definition plus
placements referencing component canvases — versioned through the same
append-only ``CanvasSourceVersion`` machinery as file projects, but never
built: layout is data, so publishing one is a metadata write.

The pure validators here mirror ``source.py``'s posture (no ORM, structured
diagnostics). Reference checks that need the database (component existence,
visibility, config-vs-schema) live in ``validate_layout_references``.
"""

import re
import json
from collections import Counter
from typing import Any, TypeGuard
from uuid import UUID

import jsonschema

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope

from products.canvas.backend.contract import GRID_COLUMN_CHOICES, MAX_COMPONENT_HEIGHT, contract_limits
from products.canvas.backend.source import diagnostic

CANVAS_LAYOUT_SCHEMA_VERSION = 1

PLACEMENT_STATUSES = ("pending", "generating", "live", "failed")
PLACEMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

MIN_ROW_HEIGHT = 24
MAX_ROW_HEIGHT = 400
MAX_GAP = 48
# Rows a layout may extend to; bounds y so a placement cannot claim an
# effectively unbounded scroll area.
MAX_GRID_ROWS = 400
# A legitimate patch edits a layout bounded by maxGridPlacements, so rewriting
# every placement plus the grid stays well inside this. The cap exists because a
# patch's transient placements never show up in the published document, so the
# document's own limits cannot bound the work an operation set costs.
MAX_LAYOUT_PATCH_OPERATIONS = 64
# Serialized ceiling for a persisted layout. Placement configs are free-form, so
# without this a grid publish (which consumes no build capacity) is an unbounded
# append-only write into object storage.
MAX_LAYOUT_BYTES = 256 * 1024

DEFAULT_LAYOUT: dict[str, Any] = {
    "schemaVersion": CANVAS_LAYOUT_SCHEMA_VERSION,
    "grid": {"columns": 6, "rowHeight": 96, "gap": 8},
    "placements": [],
}


def default_layout() -> dict[str, Any]:
    return {
        **DEFAULT_LAYOUT,
        "grid": dict(DEFAULT_LAYOUT["grid"]),
        "placements": [],
    }


def _validate_grid(grid: Any) -> list[dict[str, Any]]:
    if not isinstance(grid, dict):
        return [diagnostic("error", "invalid_grid", "layout.grid must be an object with columns, rowHeight, and gap")]
    diagnostics: list[dict[str, Any]] = []
    if grid.get("columns") not in GRID_COLUMN_CHOICES:
        diagnostics.append(
            diagnostic(
                "error",
                "invalid_grid",
                "layout.grid.columns must be one of " + ", ".join(str(choice) for choice in GRID_COLUMN_CHOICES),
            )
        )
    row_height = grid.get("rowHeight")
    if not _is_int(row_height) or not MIN_ROW_HEIGHT <= row_height <= MAX_ROW_HEIGHT:
        diagnostics.append(
            diagnostic(
                "error",
                "invalid_grid",
                f"layout.grid.rowHeight must be an integer between {MIN_ROW_HEIGHT} and {MAX_ROW_HEIGHT} pixels",
            )
        )
    gap = grid.get("gap")
    if not _is_int(gap) or not 0 <= gap <= MAX_GAP:
        diagnostics.append(
            diagnostic("error", "invalid_grid", f"layout.grid.gap must be an integer between 0 and {MAX_GAP} pixels")
        )
    return diagnostics


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _placement_label(placement: Any, index: int) -> str:
    """Name a placement by index and, when it has a usable one, by id.

    The index shifts as placements come and go, so the id is what makes two
    placements with the same field error distinguishable — which is what keeps
    ``subtract_preexisting_diagnostics`` from cancelling one against the other.
    """
    identifier = placement.get("id") if isinstance(placement, dict) else None
    if isinstance(identifier, str) and PLACEMENT_ID_RE.match(identifier):
        return f'layout.placements[{index}] ("{identifier}")'
    return f"layout.placements[{index}]"


def _validate_placement(placement: Any, index: int, columns: int) -> list[dict[str, Any]]:
    label = _placement_label(placement, index)
    if not isinstance(placement, dict):
        return [diagnostic("error", "invalid_placement", f"{label} must be an object")]
    diagnostics: list[dict[str, Any]] = []

    identifier = placement.get("id")
    if not isinstance(identifier, str) or not PLACEMENT_ID_RE.match(identifier):
        diagnostics.append(
            diagnostic(
                "error",
                "invalid_placement",
                f"{label}.id must be 1-64 characters of letters, digits, '_', or '-'",
            )
        )

    status = placement.get("status")
    if status not in PLACEMENT_STATUSES:
        diagnostics.append(
            diagnostic("error", "invalid_placement", f"{label}.status must be one of " + ", ".join(PLACEMENT_STATUSES))
        )

    for key, minimum, maximum in (
        ("x", 0, columns - 1),
        ("y", 0, MAX_GRID_ROWS - 1),
        ("w", 1, columns),
        ("h", 1, MAX_COMPONENT_HEIGHT),
    ):
        value = placement.get(key)
        if not _is_int(value) or not minimum <= value <= maximum:
            diagnostics.append(
                diagnostic(
                    "error",
                    "invalid_placement",
                    f"{label}.{key} must be an integer between {minimum} and {maximum}",
                )
            )
    if _is_int(placement.get("x")) and _is_int(placement.get("w")) and placement["x"] + placement["w"] > columns:
        diagnostics.append(
            diagnostic(
                "error",
                "invalid_placement",
                f"{label} extends past the grid's {columns} columns (x + w must be <= columns)",
            )
        )

    component = placement.get("component")
    if status == "live" and not _is_uuid(component):
        diagnostics.append(
            diagnostic("error", "invalid_placement", f"{label} is live but names no component canvas id")
        )
    if component is not None and not _is_uuid(component):
        diagnostics.append(diagnostic("error", "invalid_placement", f"{label}.component must be a canvas id"))

    version = placement.get("version")
    if version is not None and version != "latest" and not _is_uuid(version):
        diagnostics.append(
            diagnostic(
                "error",
                "invalid_placement",
                f'{label}.version must be "latest" or a source version id of the component',
            )
        )

    config = placement.get("config")
    if config is not None and not isinstance(config, dict):
        diagnostics.append(diagnostic("error", "invalid_placement", f"{label}.config must be an object"))

    prompt = placement.get("prompt")
    if prompt is not None and (not isinstance(prompt, str) or len(prompt) > 10_000):
        diagnostics.append(
            diagnostic("error", "invalid_placement", f"{label}.prompt must be a string of at most 10,000 characters")
        )

    task_id = placement.get("generationTaskId")
    if task_id is not None and not _is_uuid(task_id):
        diagnostics.append(diagnostic("error", "invalid_placement", f"{label}.generationTaskId must be a task id"))

    return diagnostics


def _overlaps(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return (
        first["x"] < second["x"] + second["w"]
        and second["x"] < first["x"] + first["w"]
        and first["y"] < second["y"] + second["h"]
        and second["y"] < first["y"] + first["h"]
    )


def validate_layout(layout: Any) -> list[dict[str, Any]]:
    """Validate a candidate layout document; pure, no ORM.

    Returns structured diagnostics; errors block publishing. Reference-level
    checks (components exist and are visible, config matches schema) are
    ``validate_layout_references``'s job.
    """
    if not isinstance(layout, dict):
        return [diagnostic("error", "invalid_layout", "the layout must be an object")]
    size = len(json.dumps(layout, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if size > MAX_LAYOUT_BYTES:
        return [
            diagnostic(
                "error",
                "layout_too_large",
                f"the layout is {size} bytes; a grid canvas may store at most {MAX_LAYOUT_BYTES} bytes of layout",
            )
        ]
    diagnostics: list[dict[str, Any]] = []
    if layout.get("schemaVersion") != CANVAS_LAYOUT_SCHEMA_VERSION:
        diagnostics.append(
            diagnostic("error", "unsupported_schema_version", f"schemaVersion must be {CANVAS_LAYOUT_SCHEMA_VERSION}")
        )
    diagnostics.extend(_validate_grid(layout.get("grid")))
    placements = layout.get("placements")
    if not isinstance(placements, list):
        return [*diagnostics, diagnostic("error", "invalid_layout", "layout.placements must be a list")]
    max_placements = contract_limits()["maxGridPlacements"]
    if len(placements) > max_placements:
        # Overlap detection below compares every placement against every earlier
        # one, so an over-cap document must never reach it.
        return [
            *diagnostics,
            diagnostic("error", "too_many_placements", f"a grid canvas may hold at most {max_placements} placements"),
        ]

    columns = layout.get("grid", {}).get("columns") if isinstance(layout.get("grid"), dict) else None
    effective_columns = columns if columns in GRID_COLUMN_CHOICES else max(GRID_COLUMN_CHOICES)
    seen_ids: set[str] = set()
    rects: list[dict[str, Any]] = []
    for index, placement in enumerate(placements):
        diagnostics.extend(_validate_placement(placement, index, effective_columns))
        if not isinstance(placement, dict):
            continue
        identifier = placement.get("id")
        if isinstance(identifier, str):
            if identifier in seen_ids:
                diagnostics.append(
                    diagnostic("error", "duplicate_placement_id", f'placement id "{identifier}" is used twice')
                )
            seen_ids.add(identifier)
        if all(_is_int(placement.get(key)) for key in ("x", "y", "w", "h")):
            for other in rects:
                if _overlaps(placement, other):
                    diagnostics.append(
                        diagnostic(
                            "error",
                            "placements_overlap",
                            f'placements "{other.get("id")}" and "{placement.get("id")}" overlap',
                        )
                    )
            rects.append(placement)
    return diagnostics


def validate_layout_references(team_id: int, user_id: int | None, layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate a layout's component references against the database.

    Only components the acting user may see (channel visibility applied) are
    placeable — a placement referencing anything else is rejected identically
    whether the component is missing, deleted, the wrong kind, or merely
    invisible, so the error does not disclose which.
    """
    from products.canvas.backend.models import (  # noqa: PLC0415 — keeps this module import-light for the pure validators
        Canvas,
        CanvasBuild,
        CanvasSourceVersion,
    )
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415 — same reason

    diagnostics: list[dict[str, Any]] = []
    referenced = [
        placement
        for placement in layout.get("placements", [])
        if isinstance(placement, dict) and _is_uuid(placement.get("component"))
    ]
    if not referenced:
        return diagnostics

    with team_scope(team_id):
        component_ids = {str(placement["component"]) for placement in referenced}
        components = {
            str(canvas.id): canvas
            for canvas in Canvas.objects.for_team(team_id)
            .filter(id__in=component_ids, kind=Canvas.KIND_COMPONENT, deleted=False)
            .filter(tasks_facade.visible_channels_q(user_id, relation="channel"))
            .select_related("current_source_version")
        }
        version_ids = {str(placement["version"]) for placement in referenced if _is_uuid(placement.get("version"))}
        # A pinned placement renders that version's artifact against that
        # version's contract, so both have to be read per version; the
        # component's head answers only for "latest" placements.
        pinned_versions = (
            {
                (str(version.canvas_id), str(version.id)): version
                for version in CanvasSourceVersion.objects.for_team(team_id).filter(id__in=version_ids, draft=False)
            }
            if version_ids
            else {}
        )
        renderable_versions = (
            set(
                CanvasBuild.objects.for_team(team_id)
                .filter(
                    source_version_id__in=[version.id for version in pinned_versions.values()],
                    status=CanvasBuild.STATUS_READY,
                    artifact_object_prefix__isnull=False,
                )
                .values_list("source_version_id", flat=True)
            )
            if pinned_versions
            else set()
        )

    for placement in referenced:
        label = f'placement "{placement.get("id")}"'
        component_id = str(placement["component"])
        component = components.get(component_id)
        if component is None:
            diagnostics.append(
                diagnostic("error", "component_not_found", f"{label} references a component that is not available")
            )
            continue
        version = placement.get("version")
        pinned = pinned_versions.get((component_id, str(version))) if _is_uuid(version) else None
        if _is_uuid(version) and pinned is None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "component_version_not_found",
                    f"{label} pins a version that is not one of the component's published versions",
                )
            )
            continue
        source_version = pinned or component.current_source_version
        meta = source_version.component_meta if source_version else None
        if not isinstance(meta, dict):
            diagnostics.append(
                diagnostic(
                    "error",
                    "component_not_published",
                    f"{label} references a component that has never published a placement contract",
                )
            )
            continue
        # A live placement renders a built artifact; without a ready build there
        # is nothing to render, so going live must wait for it. A pin is asked
        # about its own build, whose artifact may since have aged out.
        if placement.get("status") == "live":
            if pinned is not None and pinned.id not in renderable_versions:
                diagnostics.append(
                    diagnostic(
                        "error",
                        "component_build_not_ready",
                        f"{label} cannot go live: the version it pins has no build to render. "
                        "Pin a version whose build is still retained, or follow the latest one.",
                    )
                )
            elif pinned is None and component.published_build_id is None:
                diagnostics.append(
                    diagnostic(
                        "error",
                        "component_build_not_ready",
                        f"{label} cannot go live: the component has no ready build yet. Wait for its build to finish.",
                    )
                )
        size = meta.get("size") or {}
        for axis in ("W", "H"):
            value = placement.get(axis.lower())
            if not _is_int(value):
                continue
            minimum = size.get(f"min{axis}", 1)
            maximum = size.get(f"max{axis}")
            if value < minimum or (maximum is not None and value > maximum):
                cap = f"-{maximum}" if maximum is not None else "+"
                # Advisory only: the user sizes their own grid, and components
                # are responsible for rendering responsively at any box size.
                # The contract's range still informs defaults and this hint.
                diagnostics.append(
                    diagnostic(
                        "warning",
                        "placement_size_out_of_contract",
                        f"{label} is {value} {axis.lower()} units; the component suggests {minimum}{cap}",
                    )
                )
        schema = meta.get("configSchema")
        if schema is not None:
            # An omitted config is an empty config: a schema that marks fields
            # required must reject a placement that supplies none, matching how
            # it already rejects an explicit empty object.
            try:
                jsonschema.validate(placement.get("config") or {}, schema)
            except jsonschema.ValidationError as error:
                diagnostics.append(
                    diagnostic(
                        "error",
                        "placement_config_invalid",
                        f"{label} config does not match the component's schema: {error.message}",
                    )
                )
    return diagnostics


# Placement index labels shift when placements are removed; normalize them so
# a pre-existing diagnostic still matches after unrelated edits.
_PLACEMENT_INDEX_RE = re.compile(r"placements\[\d+\]")


@frozen
class _DiagnosticKey:
    severity: str
    code: str
    message: str


def _diagnostic_key(diag: dict[str, Any]) -> _DiagnosticKey:
    return _DiagnosticKey(
        severity=str(diag.get("severity", "")),
        code=str(diag.get("code", "")),
        message=_PLACEMENT_INDEX_RE.sub("placements[]", str(diag.get("message", ""))),
    )


def subtract_preexisting_diagnostics(
    candidate: list[dict[str, Any]], baseline: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Drop candidate diagnostics already present in the baseline layout.

    A patch is judged on what it changes: problems the canvas already had (a
    component deleted or republished with a stricter contract after being
    placed) must not block unrelated edits, or one rotten placement freezes
    the whole canvas.
    """
    remaining = Counter(_diagnostic_key(diag) for diag in baseline)
    fresh: list[dict[str, Any]] = []
    for diag in candidate:
        key = _diagnostic_key(diag)
        if remaining[key] > 0:
            remaining[key] -= 1
            continue
        fresh.append(diag)
    return fresh


def apply_layout_ops(
    layout: dict[str, Any], operations: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply surgical operations to a layout document.

    Returns the edited layout (input untouched) and diagnostics; any
    diagnostic means the operation set could not be applied atomically.
    Validation of the result is the caller's job.
    """
    layout = {**layout, "placements": [dict(placement) for placement in layout.get("placements", [])]}
    diagnostics: list[dict[str, Any]] = []
    max_placements = contract_limits()["maxGridPlacements"]
    by_id = {placement.get("id"): placement for placement in layout["placements"]}
    for operation in operations:
        op = operation["op"]
        if op == "set_grid":
            layout["grid"] = operation.get("grid")
        elif op == "add_placement":
            placement = operation.get("placement") or {}
            identifier = placement.get("id")
            if identifier in by_id:
                diagnostics.append(
                    diagnostic("error", "edit_target_conflict", f'a placement with id "{identifier}" already exists')
                )
                continue
            if len(layout["placements"]) >= max_placements:
                # Bound the intermediate document too: an operation set that adds
                # and removes its way past the cap costs the same work as an
                # over-cap publish while ending inside the limit.
                diagnostics.append(
                    diagnostic(
                        "error",
                        "too_many_placements",
                        f"a grid canvas may hold at most {max_placements} placements",
                    )
                )
                break
            layout["placements"].append(dict(placement))
            by_id[identifier] = layout["placements"][-1]
        elif op in ("update_placement", "remove_placement"):
            identifier = operation.get("id")
            existing = by_id.get(identifier)
            if existing is None:
                diagnostics.append(
                    diagnostic("error", "edit_target_missing", f'the layout has no placement with id "{identifier}"')
                )
                continue
            if op == "remove_placement":
                layout["placements"].remove(existing)
                del by_id[identifier]
            else:
                update = {key: value for key, value in (operation.get("changes") or {}).items() if key != "id"}
                existing.update(update)
    return layout, diagnostics
