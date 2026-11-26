"""The schema of a stored `dashboard-v2` board document, and how an old document becomes the current one.

A document carries its own schema version in `version`. Each entry of `UPGRADES` takes a document at one schema
version and returns it at the next, without I/O, so a stored board is upgraded when it is read and never needs a
bulk data migration. Saves store the current schema version. Fields this code does not know pass through
unchanged, so a save from an older client never strips a field a newer one added. The scene's client applies the
same rules.
"""

import json
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
    while schema_version < CURRENT_SCHEMA_VERSION:
        spec = UPGRADES[schema_version](spec)
        schema_version += 1
        spec = {**spec, "version": schema_version}
    return spec


def check_size(spec: dict[str, Any]) -> None:
    size = len(json.dumps(spec, separators=(",", ":")).encode())
    if size > MAX_BOARD_SPEC_BYTES:
        raise BoardSpecInvalid(f"The board document is {size} bytes. The limit is {MAX_BOARD_SPEC_BYTES} bytes.")


def _has_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(key) or _has_nul(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_nul(item) for item in value)
    return False


def check_storable(spec: dict[str, Any]) -> None:
    # Postgres refuses a NUL character anywhere in a jsonb value, so the save would fail with a 500.
    if _has_nul(spec):
        raise BoardSpecInvalid("The board document contains a NUL character (\\u0000), which cannot be saved.")


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
