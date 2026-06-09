"""Pure data layer for tools.yaml: schema, parsing, persistence, and the
generated artifacts (compose override + user Dockerfile). No docker calls,
no interactive prompts, no side effects at import. Shares the catalog/user-file
YAML format with MCP servers via sandbox_addons; adds the tool-specific schema
and apply logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
import sandbox_addons
from sandbox_addons import REGISTRY_DIR, AddonError

TOOLS_FILE = REGISTRY_DIR / "tools.yaml"
TOOL_AUTH_COMPOSE_FILE = REGISTRY_DIR / "docker-compose.tool-auth.yml"
USER_DOCKERFILE = REGISTRY_DIR / "Dockerfile.user"

SANDBOX_DOCKERFILE = Path(__file__).resolve().parent.parent / "Dockerfile.sandbox"

# In-sandbox $HOME. Must stay in sync with SANDBOX_HOME in
# bin/sandbox-entrypoint.py; this is what ~ resolves to inside the container.
SANDBOX_HOME_IN_CONTAINER = "/home/sandbox"


def expand_sandbox_path(raw: str) -> str:
    """Expand ~ / ~/foo to the sandbox $HOME path. Everything else passes through."""
    if raw == "~":
        return SANDBOX_HOME_IN_CONTAINER
    if raw.startswith("~/"):
        return f"{SANDBOX_HOME_IN_CONTAINER}/{raw[2:]}"
    return raw


@dataclass
class ToolCopy:
    # Stored exactly as written in tools.yaml. ~ expands per side at copy time:
    # host via Path.expanduser(), container via expand_sandbox_path().
    source: str
    target: str


@dataclass
class Tool:
    name: str
    install: str | None = None
    copy: list[ToolCopy] = field(default_factory=list)
    # Catalog-only metadata. None in user tools.yaml; populated when loaded
    # from bin/sandbox-tools.yaml. save_user_tools never persists it.
    description: str | None = None


def parse_tool_copy(entry: object, *, source_label: str) -> ToolCopy:
    """Short form (one string used for both sides) or long form ({source, target})."""
    if isinstance(entry, str):
        return ToolCopy(source=entry, target=entry)
    if isinstance(entry, dict):
        return ToolCopy(source=str(entry["source"]), target=str(entry["target"]))
    raise AddonError(f"{source_label}: invalid copy entry {entry!r} (expected string or mapping).")


def _parse_entry(raw: dict) -> Tool:
    # name presence/uniqueness is validated by sandbox_addons.load_named_entries.
    name = raw["name"]
    # Migration guard: 'mounts' was renamed to 'copy' in a recent commit.
    if "mounts" in raw:
        raise AddonError(
            f"tool {name!r} uses 'mounts:' which was renamed to 'copy:'. "
            "Edit the YAML key (the field semantics are unchanged)."
        )
    copy = [parse_tool_copy(c, source_label=f"tool {name!r} copy[{i}]") for i, c in enumerate(raw.get("copy") or [])]
    return Tool(name=name, install=raw.get("install"), copy=copy, description=raw.get("description") or None)


def load_user_tools() -> list[Tool]:
    return sandbox_addons.load_entries(TOOLS_FILE, "tools", _parse_entry)


def load_catalog(catalog_file: Path) -> dict[str, Tool]:
    # Catalog Tool instances have `description` set; user tools.yaml does not.
    return sandbox_addons.load_catalog(catalog_file, "tools", _parse_entry)


def resolved_tools(catalog_file: Path) -> list[tuple[str, str]]:
    """Return (name, description) for the user's selected tools.

    Descriptions come from the catalog, since the user tools.yaml doesn't store
    them; tools added ad hoc (not in the catalog) get an empty description.
    bin/sandbox uses this to list installed tools in the sandbox CLAUDE.md.
    """
    catalog = load_catalog(catalog_file)
    return [(t.name, (catalog[t.name].description if t.name in catalog else None) or "") for t in load_user_tools()]


def _format_copy(c: ToolCopy) -> str | dict[str, str]:
    return c.source if c.source == c.target else {"source": c.source, "target": c.target}


def save_user_tools(tools: list[Tool]) -> None:
    entries: list[dict] = []
    for t in tools:
        entry: dict = {"name": t.name}
        if t.install is not None:
            entry["install"] = t.install if t.install.endswith("\n") else t.install + "\n"
        if t.copy:
            entry["copy"] = [_format_copy(c) for c in t.copy]
        entries.append(entry)
    sandbox_addons.save_named_entries(TOOLS_FILE, "tools", entries)


def write_user_dockerfile(tools: list[Tool], *, out: Path = USER_DOCKERFILE) -> Path:
    # Inlines the base Dockerfile and appends a RUN block per tool. Docker's
    # BuildKit layer cache shares the base content across users by content,
    # so there is no separate base-image tag to manage.
    #
    # Creates the sandbox user at build time with home = SANDBOX_HOME_IN_CONTAINER
    # (the same path the entrypoint uses at runtime) so `npm install -g` etc. and
    # ~ resolve consistently. The entrypoint's create_sandbox_user is idempotent:
    # it skips when this build-time user already exists.
    home = SANDBOX_HOME_IN_CONTAINER
    parts = [
        SANDBOX_DOCKERFILE.read_text().rstrip(),
        "\n\n# --- Personal tool layers (generated from ~/.posthog-sandboxes/tools.yaml) ---\n",
        "ARG SANDBOX_UID\nARG SANDBOX_GID\n\n",
        "RUN groupadd -g ${SANDBOX_GID} sandbox 2>/dev/null || true \\\n",
        f" && useradd  -u ${{SANDBOX_UID}} -g ${{SANDBOX_GID}} -d {home} -m -s /bin/bash sandbox\n\n",
        "USER sandbox\n",
        f"ENV NPM_CONFIG_PREFIX={home}/.npm-global\n",
        f"ENV PATH={home}/.npm-global/bin:{home}/.local/bin:${{PATH}}\n",
        f"RUN mkdir -p {home}/.npm-global/bin {home}/.local/bin\n\n",
    ]
    for t in tools:
        snippet = (t.install or "").strip()
        if not snippet:
            continue
        parts.append(f"# Tool: {t.name}\n")
        parts.append("RUN <<'__POSTHOG_SANDBOX_EOF__'\nset -e\n")
        parts.append(snippet + "\n")
        parts.append("__POSTHOG_SANDBOX_EOF__\n\n")
    parts.append("USER root\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(parts))
    return out


def write_user_image_compose(*, dockerfile: Path) -> Path:
    # Override that points `build.dockerfile` at the per-user Dockerfile
    # generated from tools.yaml. Rewritten before every `docker compose`
    # call; tools.yaml is the source of truth so there's no cache to
    # invalidate.
    TOOL_AUTH_COMPOSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOOL_AUTH_COMPOSE_FILE, "w") as f:
        yaml.safe_dump(
            {"services": {"app": {"build": {"dockerfile": str(dockerfile)}}}},
            f,
            sort_keys=False,
        )
    return TOOL_AUTH_COMPOSE_FILE
