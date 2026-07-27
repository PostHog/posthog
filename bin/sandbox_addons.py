"""Shared format for sandbox addons (tools, MCP servers): named entries chosen
from a checked-in YAML catalog into a per-user YAML file. Owns the read/write
plumbing, the registry path, and the error type; per-type schema and apply logic
live in sandbox_tools.py / sandbox_mcp.py.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypeVar

import yaml

REGISTRY_DIR = Path.home() / ".posthog-sandboxes"


class AddonError(Exception):
    """Raised on any malformed catalog or user-file entry."""


class _Named(Protocol):
    name: str


_T = TypeVar("_T", bound=_Named)


class _BlockLiteralDumper(yaml.SafeDumper):
    """Renders multi-line strings as `|` blocks (e.g. tool install scripts)."""


def _block_literal_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_BlockLiteralDumper.add_representer(str, _block_literal_str)


def load_named_entries(path: Path, section: str) -> list[dict]:
    """Read the `section:` list as raw dicts, validating unique non-empty names.

    Returns [] when the file is absent.
    """
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    entries: list[dict] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw.get(section) or []):
        label = f"{path}: {section}[{i}]"
        if not isinstance(entry, dict):
            raise AddonError(f"{label}: must be a mapping.")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AddonError(f"{label}: 'name' is required and must be a non-empty string.")
        if name in seen:
            raise AddonError(f"{path}: duplicate name {name!r}.")
        seen.add(name)
        entries.append(entry)
    return entries


def save_named_entries(path: Path, section: str, entries: list[dict], *, mode: int | None = None) -> None:
    """Write `entries` under the `section:` key, preserving order and block scalars."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            {section: entries},
            Dumper=_BlockLiteralDumper,
            sort_keys=False,
            default_flow_style=False,
            indent=2,
        )
    )
    if mode is not None:
        path.chmod(mode)


def load_entries(path: Path, section: str, parse: Callable[[dict], _T]) -> list[_T]:
    """Parse each `section:` entry from a YAML file into a typed object."""
    return [parse(entry) for entry in load_named_entries(path, section)]


def load_catalog(path: Path, section: str, parse: Callable[[dict], _T]) -> dict[str, _T]:
    """Like load_entries, but keyed by entry name for catalog lookups."""
    return {entry.name: entry for entry in load_entries(path, section, parse)}
