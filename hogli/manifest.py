"""Manifest loading and discovery for hogli commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = Path(__file__).parent / "scripts_manifest.yaml"


class Manifest:
    """Encapsulates manifest loading and discovery operations."""

    def __init__(self) -> None:
        """Load manifest from YAML file."""
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        """Load scripts manifest from YAML file."""
        if not MANIFEST_FILE.exists():
            return {}
        with open(MANIFEST_FILE) as f:
            return yaml.safe_load(f) or {}

    @property
    def data(self) -> dict[str, Any]:
        """Get raw manifest data."""
        return self._data

    @property
    def categories(self) -> dict[str, Any]:
        """Get category metadata."""
        return self._data.get("metadata", {}).get("categories", {})

    @property
    def services(self) -> dict[str, Any]:
        """Get service metadata."""
        return self._data.get("metadata", {}).get("services", {})

    def get_category_for_command(self, command_name: str) -> str:
        """Infer category title for a command from its prefix.

        For example:
        - "test:python" has prefix "test" → searches for commands with "test:" prefix
        - Finds them in "testing" category → returns the category title from metadata
        - Falls back to "commands" if prefix not found in any category
        """
        # Extract prefix from command name (e.g., "test:python" → "test")
        prefix = command_name.split(":")[0]

        # Search through manifest categories to find which one has commands with this prefix
        for category_key, commands in self._data.items():
            if category_key == "metadata":
                continue
            if not isinstance(commands, dict):
                continue

            # Check if any command in this category starts with the prefix
            for cmd_name in commands.keys():
                if cmd_name.startswith(f"{prefix}:") or cmd_name == prefix:
                    # Found category containing this prefix! Return its title
                    category_title = self.categories.get(category_key, {}).get("title", category_key.replace("_", " "))
                    return category_title

        # Fallback if prefix not found in any category
        return "commands"

    def get_services_for_command(self, command_name: str, command_config: dict) -> list[tuple[str, str]]:
        """Get service info for a command as (name, about) tuples.

        If command has explicit 'services' field, use those.
        Otherwise, try to match command prefix to a service name.
        Returns list of (service_name, about) tuples.
        """
        # If explicit services specified, use those
        explicit_services = command_config.get("services", [])
        if explicit_services:
            result = []
            for svc in explicit_services:
                if svc in self.services:
                    svc_info = self.services[svc]
                    result.append((svc_info.get("name", svc), svc_info.get("about", "")))
            return result

        # Try to match command prefix to service
        prefix = command_name.split(":")[0]
        if prefix in self.services:
            svc_info = self.services[prefix]
            return [(svc_info.get("name", prefix), svc_info.get("about", ""))]

        return []


# Singleton instance for convenience
_manifest_instance: Manifest | None = None


def get_manifest() -> Manifest:
    """Get or create the manifest singleton."""
    global _manifest_instance
    if _manifest_instance is None:
        _manifest_instance = Manifest()
    return _manifest_instance


# Legacy convenience functions for backwards compatibility
def load_manifest() -> dict[str, Any]:
    """Load scripts manifest from YAML file."""
    return get_manifest().data


def get_category_for_command(command_name: str) -> str:
    """Infer category title for a command from its prefix."""
    return get_manifest().get_category_for_command(command_name)


def get_services_for_command(command_name: str, command_config: dict) -> list[tuple[str, str]]:
    """Get service info for a command."""
    return get_manifest().get_services_for_command(command_name, command_config)
