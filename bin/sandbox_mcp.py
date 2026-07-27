"""Remote MCP server schema for mcps.yaml: secret templating, persistence, and
the resolved JSON the sandbox entrypoint merges into Claude. Shares the
catalog/user-file YAML format with tools via sandbox_addons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import sandbox_addons
from sandbox_addons import REGISTRY_DIR, AddonError

MCP_FILE = REGISTRY_DIR / "mcps.yaml"


@dataclass
class Mcp:
    name: str
    server: dict  # value Claude expects under mcpServers[name]
    # Catalog-only; never written to the user file.
    description: str | None = None
    # Env vars (set in sandbox.env) that this server's config references via ${VAR}.
    env: list[str] = field(default_factory=list)


def _parse_entry(raw: dict) -> Mcp:
    # name presence/uniqueness is validated by sandbox_addons.load_named_entries.
    name = raw["name"]
    server = raw.get("server")
    if not isinstance(server, dict):
        raise AddonError(f"mcp {name!r}: 'server' is required and must be a mapping.")
    env = raw.get("env") or []
    if not isinstance(env, list) or not all(isinstance(s, str) for s in env):
        raise AddonError(f"mcp {name!r}: 'env' must be a list of strings.")
    return Mcp(name=name, server=server, description=raw.get("description") or None, env=env)


def load_user_mcps() -> list[Mcp]:
    return sandbox_addons.load_entries(MCP_FILE, "mcps", _parse_entry)


def load_catalog(catalog_file: Path) -> dict[str, Mcp]:
    return sandbox_addons.load_catalog(catalog_file, "mcps", _parse_entry)


def save_user_mcps(mcps: list[Mcp]) -> None:
    # Servers reference secrets as ${VAR} (set in sandbox.env), so the file
    # itself holds no tokens.
    entries = [{"name": m.name, "server": m.server} for m in mcps]
    sandbox_addons.save_named_entries(MCP_FILE, "mcps", entries)


def resolve_servers() -> dict[str, dict]:
    return {m.name: m.server for m in load_user_mcps()}
