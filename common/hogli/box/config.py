"""Local config helpers for hogli box preferences."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class BoxConfig(TypedDict, total=False):
    git_name: str
    git_email: str


def get_config_path() -> Path:
    """Return the config path for persisted hogli box preferences."""
    return Path.home() / ".config" / "posthog" / "hogli_box.json"


def load_config() -> BoxConfig:
    """Load persisted hogli box preferences from disk."""
    try:
        data = json.loads(get_config_path().read_text())
    except Exception:
        return BoxConfig()

    if not isinstance(data, dict):
        return BoxConfig()

    config = BoxConfig()
    for key in ("git_name", "git_email"):
        value = data.get(key)
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value:
                config[key] = stripped_value
    return config


def save_config(config: BoxConfig) -> None:
    """Persist hogli box preferences to disk."""
    normalized = BoxConfig()
    for key in ("git_name", "git_email"):
        value = config.get(key)
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value:
                normalized[key] = stripped_value

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2) + "\n")


def save_git_identity(git_name: str, git_email: str) -> BoxConfig:
    """Persist Git identity defaults for new workspaces."""
    config = load_config()
    config["git_name"] = git_name
    config["git_email"] = git_email
    save_config(config)
    return config
