"""Remote MCP server schema for mcps.yaml: secret templating, persistence, and
the resolved JSON the sandbox entrypoint merges into Claude. Shares the
catalog/user-file YAML format with tools via sandbox_addons.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

import sandbox_addons
from sandbox_addons import REGISTRY_DIR, AddonError

MCP_FILE = REGISTRY_DIR / "mcps.yaml"
# Resolved {"mcpServers": {...}} written at create time and bind-mounted into the
# container, where the entrypoint reads it with stdlib json (no PyYAML at boot).
# Holds auth tokens, hence mode 0600.
MCP_SERVERS_FILE = REGISTRY_DIR / "mcp-servers.json"


@dataclass
class Mcp:
    name: str
    server: dict  # value Claude expects under mcpServers[name]
    # Catalog-only; never written to the user file.
    description: str | None = None
    secrets: list[str] = field(default_factory=list)


def _parse_entry(raw: dict) -> Mcp:
    # name presence/uniqueness is validated by sandbox_addons.load_named_entries.
    name = raw["name"]
    server = raw.get("server")
    if not isinstance(server, dict):
        raise AddonError(f"mcp {name!r}: 'server' is required and must be a mapping.")
    secrets = raw.get("secrets") or []
    if not isinstance(secrets, list) or not all(isinstance(s, str) for s in secrets):
        raise AddonError(f"mcp {name!r}: 'secrets' must be a list of strings.")
    return Mcp(name=name, server=server, description=raw.get("description") or None, secrets=secrets)


def load_user_mcps() -> list[Mcp]:
    return sandbox_addons.load_entries(MCP_FILE, "mcps", _parse_entry)


def load_catalog(catalog_file: Path) -> dict[str, Mcp]:
    return sandbox_addons.load_catalog(catalog_file, "mcps", _parse_entry)


def save_user_mcps(mcps: list[Mcp]) -> None:
    entries = [{"name": m.name, "server": m.server} for m in mcps]
    # Resolved secrets live in `server`, so keep the file private.
    sandbox_addons.save_named_entries(MCP_FILE, "mcps", entries, mode=0o600)


def _substitute(value: object, secrets: dict[str, str]) -> object:
    if isinstance(value, str):
        return Template(value).safe_substitute(secrets)
    if isinstance(value, dict):
        return {k: _substitute(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, secrets) for v in value]
    return value


def fill_secrets(server: dict, secrets: dict[str, str]) -> dict:
    """Substitute ${name} placeholders in a server dict with prompted secrets.

    safe_substitute leaves an unrelated ${VAR} for Claude to expand at runtime.
    """
    return {key: _substitute(value, secrets) for key, value in server.items()}


def resolve_servers() -> dict[str, dict]:
    return {m.name: m.server for m in load_user_mcps()}


def write_resolved_servers(out: Path = MCP_SERVERS_FILE) -> Path | None:
    """Serialize the user's servers to {"mcpServers": {...}} for the entrypoint.

    Returns the path, or None when nothing is configured so callers can fall
    back to a /dev/null bind mount.
    """
    servers = resolve_servers()
    if not servers:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n")
    out.chmod(0o600)
    return out
