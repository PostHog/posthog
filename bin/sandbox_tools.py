"""Pure data layer for tools.yaml: schema, parsing, persistence, and the
generated artifacts (compose override + user Dockerfile). No docker calls,
no interactive prompts, no side effects at import. Callers wrap ToolsError
with their own error reporter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REGISTRY_DIR = Path.home() / ".posthog-sandboxes"
TOOLS_FILE = REGISTRY_DIR / "tools.yaml"
TOOL_AUTH_COMPOSE_FILE = REGISTRY_DIR / "docker-compose.tool-auth.yml"
USER_DOCKERFILE = REGISTRY_DIR / "Dockerfile.user"

SANDBOX_DOCKERFILE = Path(__file__).resolve().parent.parent / "Dockerfile.sandbox"

# In-sandbox $HOME. Must stay in sync with SANDBOX_HOME in
# bin/sandbox-entrypoint.py; tools.yaml copy targets resolve here.
SANDBOX_HOME_IN_CONTAINER = "/tmp/sandbox-home"


class ToolsError(Exception):
    """Raised on any malformed tools.yaml or catalog entry."""


@dataclass
class ToolCopy:
    # Seeded once at create time via `docker cp` from the host; the container
    # owns the file thereafter (token refresh, re-auth, etc. stay inside).
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


class _BlockLiteralDumper(yaml.SafeDumper):
    # Scoped subclass so the str representer below doesn't mutate yaml.SafeDumper globally.
    pass


def _block_literal_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_BlockLiteralDumper.add_representer(str, _block_literal_str)


def parse_tool_copy(entry: object, *, source_label: str) -> ToolCopy:
    # Short form ("~/path") or long form ({source, target}). ToolsError on
    # short form not under $HOME, ~user targets, or targets outside sandbox $HOME.
    host_home = str(Path.home())
    if isinstance(entry, str):
        source = str(Path(entry).expanduser().resolve(strict=False))
        try:
            rel = Path(source).relative_to(host_home)
        except ValueError:
            raise ToolsError(
                f"{source_label}: short-form copy entry {entry!r} is not under "
                f"$HOME ({host_home}). Use long form: "
                "{source: /abs/path, target: ~/...}."
            )
        return ToolCopy(source=source, target=f"{SANDBOX_HOME_IN_CONTAINER}/{rel}")

    if isinstance(entry, dict):
        source = str(Path(entry["source"]).expanduser().resolve(strict=False))
        target_raw = str(entry["target"])
        if target_raw.startswith("~/"):
            target = f"{SANDBOX_HOME_IN_CONTAINER}/{target_raw[2:]}"
        elif target_raw == "~":
            target = SANDBOX_HOME_IN_CONTAINER
        elif target_raw.startswith("~"):
            raise ToolsError(
                f"{source_label}: target {target_raw!r} uses '~user' which is "
                "not supported. Use '~/...' or an absolute path under "
                f"{SANDBOX_HOME_IN_CONTAINER}."
            )
        else:
            target = target_raw
        if target != SANDBOX_HOME_IN_CONTAINER and not target.startswith(SANDBOX_HOME_IN_CONTAINER + "/"):
            raise ToolsError(
                f"{source_label}: target {entry['target']!r} must resolve "
                f"under sandbox $HOME ({SANDBOX_HOME_IN_CONTAINER})."
            )
        return ToolCopy(source=source, target=target)

    raise ToolsError(f"{source_label}: invalid copy entry {entry!r} (expected string or mapping).")


def _parse_entry(raw: dict, *, label: str) -> Tool:
    # Migration guard: 'mounts' was renamed to 'copy' in a recent commit.
    if "mounts" in raw:
        raise ToolsError(
            f"{label} uses 'mounts:' which was renamed to 'copy:'. "
            "Edit the YAML key (the field semantics are unchanged)."
        )
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolsError(f"{label}: 'name' is required and must be a non-empty string.")
    copy = [parse_tool_copy(c, source_label=f"{label}.copy[{i}]") for i, c in enumerate(raw.get("copy") or [])]
    return Tool(name=name, install=raw.get("install"), copy=copy, description=raw.get("description") or None)


def _load_tools(path: Path) -> list[Tool]:
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    tools: list[Tool] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw.get("tools") or []):
        tool = _parse_entry(entry, label=f"{path}: tools[{i}]")
        if tool.name in seen:
            raise ToolsError(f"{path}: duplicate tool name {tool.name!r}.")
        seen.add(tool.name)
        tools.append(tool)
    return tools


def load_user_tools() -> list[Tool]:
    return _load_tools(TOOLS_FILE)


def load_catalog(catalog_file: Path) -> dict[str, Tool]:
    # Catalog Tool instances have `description` set; user tools.yaml does not.
    return {t.name: t for t in _load_tools(catalog_file)}


def _format_copy(c: ToolCopy, host_home: Path) -> str | dict[str, str]:
    # Prefer short form when source is under $HOME and target is the default.
    try:
        rel = Path(c.source).relative_to(host_home)
    except ValueError:
        rel = None
    if rel is not None and c.target == f"{SANDBOX_HOME_IN_CONTAINER}/{rel}":
        return f"~/{rel}"

    target = c.target
    if target == SANDBOX_HOME_IN_CONTAINER:
        target = "~"
    elif target.startswith(SANDBOX_HOME_IN_CONTAINER + "/"):
        target = "~/" + target[len(SANDBOX_HOME_IN_CONTAINER) + 1 :]
    return {"source": c.source, "target": target}


def save_user_tools(tools: list[Tool]) -> None:
    host_home = Path.home()
    entries: list[dict] = []
    for t in tools:
        entry: dict = {"name": t.name}
        if t.install is not None:
            entry["install"] = t.install if t.install.endswith("\n") else t.install + "\n"
        if t.copy:
            entry["copy"] = [_format_copy(c, host_home) for c in t.copy]
        entries.append(entry)
    TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOOLS_FILE.write_text(
        yaml.dump(
            {"tools": entries},
            Dumper=_BlockLiteralDumper,
            sort_keys=False,
            default_flow_style=False,
            indent=2,
        )
    )


def write_user_dockerfile(tools: list[Tool], *, out: Path = USER_DOCKERFILE) -> Path:
    # Inlines the base Dockerfile and appends a RUN block per tool. Docker's
    # BuildKit layer cache shares the base content across users by content,
    # so there is no separate base-image tag to manage.
    #
    # Creates the sandbox user at build time so `npm install -g` etc. resolve
    # against /home/sandbox; the entrypoint's create_sandbox_user is idempotent.
    parts = [
        SANDBOX_DOCKERFILE.read_text().rstrip(),
        "\n\n# --- Personal tool layers (generated from ~/.posthog-sandboxes/tools.yaml) ---\n",
        "ARG SANDBOX_UID\nARG SANDBOX_GID\n\n",
        "RUN groupadd -g ${SANDBOX_GID} sandbox 2>/dev/null || true \\\n",
        " && useradd  -u ${SANDBOX_UID} -g ${SANDBOX_GID} -m -s /bin/bash sandbox\n\n",
        "USER sandbox\n",
        "ENV NPM_CONFIG_PREFIX=/home/sandbox/.npm-global\n",
        "ENV PATH=/home/sandbox/.npm-global/bin:/home/sandbox/.local/bin:${PATH}\n",
        "RUN mkdir -p /home/sandbox/.npm-global/bin /home/sandbox/.local/bin\n\n",
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
