"""Manifest loading and discovery for hogli commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
MANIFEST_FILE = Path(__file__).parent.parent / "manifest.yaml"


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
    def categories(self) -> list[dict[str, Any]]:
        """Get category metadata as list."""
        return self._data.get("metadata", {}).get("categories", [])

    def get_category_title(self, category_key: str) -> str:
        """Get title for a category key."""
        cat = next((c for c in self.categories if c.get("key") == category_key), None)
        return cat.get("title", category_key.replace("_", " ")) if cat else category_key.replace("_", " ")

    @property
    def services(self) -> dict[str, Any]:
        """Get service metadata."""
        return self._data.get("metadata", {}).get("services", {})

    def get_category_for_command(self, command_name: str) -> str:
        """Get category for a command based on which section it's placed in.

        For manifest commands: Uses explicit placement in category sections.
        For Click-only commands: Infers category from prefix matching.

        Example:
        - "test:python" in "tests:" section → "Run tests" category (explicit)
        - "my:custom" Click command → looks for "my:" prefix → infers category (fallback)

        Falls back to "commands" if not found in any category section.
        """
        # First, check if command is directly in a manifest section (explicit placement)
        for category_key, commands in self._data.items():
            if category_key == "metadata" or not isinstance(commands, dict):
                continue

            if command_name in commands:
                return self.get_category_title(category_key)

        # For Click-only commands not in manifest, infer from prefix
        # This allows Click commands to be categorized based on related manifest commands
        prefix = command_name.split(":")[0] if ":" in command_name else command_name

        for category_key, commands in self._data.items():
            if category_key == "metadata" or not isinstance(commands, dict):
                continue

            # Check if any manifest command shares this prefix
            if any(cmd_name.startswith(f"{prefix}:") or cmd_name == prefix for cmd_name in commands.keys()):
                return self.get_category_title(category_key)

        # Fallback if command not found and no prefix match
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
            return [
                (svc_info.get("name", svc), svc_info.get("about", ""))
                for svc in explicit_services
                if (svc_info := self.services.get(svc))
            ]

        # Try to match command prefix to service
        prefix = command_name.split(":")[0]
        if prefix in self.services:
            svc_info = self.services[prefix]
            return [(svc_info.get("name", prefix), svc_info.get("about", ""))]

        return []

    def get_all_commands(self) -> list[str]:
        """Get all available commands from the manifest."""
        commands: list[str] = []
        for category in self._data.values():
            if isinstance(category, dict) and category is not self._data.get("metadata"):
                commands.extend(category.keys())
        return commands

    def get_command_config(self, command_name: str) -> dict | None:
        """Get configuration for a specific command."""
        for category in self._data.values():
            if isinstance(category, dict) and category is not self._data.get("metadata"):
                if command_name in category:
                    return category[command_name]
        return None


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
