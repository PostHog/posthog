"""Manifest loading and discovery for hogli commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = Path(__file__).parent / "scripts_manifest.yaml"


def load_manifest() -> dict[str, Any]:
    """Load scripts manifest from YAML file."""
    if not MANIFEST_FILE.exists():
        return {}
    with open(MANIFEST_FILE) as f:
        return yaml.safe_load(f) or {}


def get_category_for_command(command_name: str) -> str:
    """Infer category title for a command from its prefix by searching manifest.

    For example:
    - "test:python" has prefix "test" → searches for commands in manifest with "test:" prefix
    - Finds them in "testing" category → returns the category title from metadata
    - Falls back to "commands" if prefix not found in any category
    """
    manifest = load_manifest()
    metadata = manifest.get("metadata", {}).get("categories", {})

    # Extract prefix from command name (e.g., "test:python" → "test")
    prefix = command_name.split(":")[0]

    # Search through manifest categories to find which one has commands with this prefix
    for category_key, commands in manifest.items():
        if category_key == "metadata":
            continue
        if not isinstance(commands, dict):
            continue

        # Check if any command in this category starts with the prefix
        for cmd_name in commands.keys():
            if cmd_name.startswith(f"{prefix}:") or cmd_name == prefix:
                # Found category containing this prefix! Return its title
                category_title = metadata.get(category_key, {}).get("title", category_key.replace("_", " "))
                return category_title

    # Fallback if prefix not found in any category (graceful degradation)
    return "commands"
