"""The schema of a stored `dashboard-v2` board document, and how an old document becomes the current one.

A document carries its own schema version in `version`. Each entry of `UPGRADES` takes a document at one schema
version and returns it at the next, without I/O, so a stored board is upgraded when it is read and never needs a
bulk data migration. Saves store the current schema version. Fields this code does not know pass through
unchanged, so a save from an older client never strips a field a newer one added. The scene's client applies the
same rules.
"""

import json
import math
from collections.abc import Callable
from typing import Any

from products.dashboards.backend.facade.contracts import MAX_BOARD_SPEC_BYTES, BoardSpecInvalid

# Version 1 is the classic dashboard, which is not stored as a document.
FIRST_SCHEMA_VERSION = 2
CURRENT_SCHEMA_VERSION = 2

# Keyed by the schema version an upgrade starts from. Add `n: upgrade_n_to_n_plus_1` and raise
# CURRENT_SCHEMA_VERSION together.
UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}

UNTITLED_BOARD = "Untitled board"


def rename_legacy_panel_fields(spec: dict[str, Any]) -> dict[str, Any]:
    """Return the document with a tile's `widget` named `panel` and the document's `widgets` named `panels`.

    Version 2 documents written before panels were named panels use the old names. The rename keeps the schema
    version, because no board was stored under the old names.
    """
    spec = dict(spec)
    if "widgets" in spec and "panels" not in spec:
        spec["panels"] = spec.pop("widgets")
    tabs = spec.get("tabs")
    if not isinstance(tabs, list):
        return spec
    spec["tabs"] = [dict(tab) if isinstance(tab, dict) else tab for tab in tabs]
    # A loop over a stack, not recursion, so a deeply nested hostile document cannot exhaust Python's stack.
    holders: list[dict[str, Any]] = [tab for tab in spec["tabs"] if isinstance(tab, dict)]
    while holders:
        holder = holders.pop()
        tiles = holder.get("tiles")
        if not isinstance(tiles, list):
            continue
        holder["tiles"] = [dict(tile) if isinstance(tile, dict) else tile for tile in tiles]
        for tile in holder["tiles"]:
            if not isinstance(tile, dict):
                continue
            if "widget" in tile and "panel" not in tile:
                tile["panel"] = tile.pop("widget")
            panel = tile.get("panel")
            if isinstance(panel, dict) and isinstance(panel.get("tiles"), list):
                tile["panel"] = dict(panel)
                holders.append(tile["panel"])
    return spec


def upgrade(spec: dict[str, Any]) -> dict[str, Any]:
    """Return the document at `CURRENT_SCHEMA_VERSION`. Raise `BoardSpecInvalid` for a version this code can't read."""
    schema_version = spec.get("version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or not FIRST_SCHEMA_VERSION <= schema_version <= CURRENT_SCHEMA_VERSION
    ):
        raise BoardSpecInvalid(
            f"The board document's `version` must be a schema version from {FIRST_SCHEMA_VERSION} to "
            f"{CURRENT_SCHEMA_VERSION}."
        )
    spec = rename_legacy_panel_fields(spec)
    while schema_version < CURRENT_SCHEMA_VERSION:
        spec = UPGRADES[schema_version](spec)
        schema_version += 1
        spec = {**spec, "version": schema_version}
    return spec


def check_size(spec: dict[str, Any]) -> None:
    size = len(json.dumps(spec, separators=(",", ":")).encode())
    if size > MAX_BOARD_SPEC_BYTES:
        raise BoardSpecInvalid(f"The board document is {size} bytes. The limit is {MAX_BOARD_SPEC_BYTES} bytes.")


# Deeper than any real board. `json.dumps` recurses once per level, so an unbounded document could crash a save.
MAX_BOARD_DEPTH = 100


def check_storable(spec: Any) -> None:
    """Refuse a document nested too deep, or holding a value Postgres refuses in jsonb, before it fails a save with a 500.

    The walk uses an explicit stack, because a hostile document can nest deeper than Python's recursion limit.
    """
    stack = [(spec, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, str):
            if "\x00" in value:
                raise BoardSpecInvalid("The board document contains a NUL character (\\u0000), which cannot be saved.")
            # A lone surrogate such as \ud800 parses into a str that has no UTF-8 form.
            if not value.isascii():
                try:
                    value.encode()
                except UnicodeEncodeError:
                    raise BoardSpecInvalid("The board document contains an unpaired surrogate, which cannot be saved.")
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise BoardSpecInvalid("The board document contains NaN or an infinite number, which cannot be saved.")
        elif isinstance(value, dict | list):
            if depth > MAX_BOARD_DEPTH:
                raise BoardSpecInvalid(f"The board document is nested deeper than {MAX_BOARD_DEPTH} levels.")
            children = [*value.keys(), *value.values()] if isinstance(value, dict) else value
            stack.extend((child, depth + 1) for child in children)


def title_of(spec: dict[str, Any]) -> str:
    title = spec.get("title")
    name = title.strip() if isinstance(title, str) else ""
    return (name or UNTITLED_BOARD)[:400]


def tags_of(spec: dict[str, Any]) -> list[str]:
    tags = spec.get("tags")
    if not isinstance(tags, list):
        return []
    return list(dict.fromkeys(tag[:100] for tag in tags if isinstance(tag, str) and tag))[:50]


def folder_of(spec: dict[str, Any]) -> str:
    folder = spec.get("folder")
    return folder[:500] if isinstance(folder, str) else ""
