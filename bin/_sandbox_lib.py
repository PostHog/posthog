"""Shared utilities for sandbox and sandbox_cloud modules."""

from __future__ import annotations

import os
import re
import sys
import time
import subprocess
from pathlib import Path
from typing import NoReturn

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = Path.home() / ".posthog-sandboxes"
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
PORT_BASE = 48001

CLOUD_CONFIG_FILE = REGISTRY_DIR / "cloud-config.json"
CLOUD_INIT_TEMPLATE = REPO_ROOT / "infra" / "cloud-sandbox" / "cloud-init.sh"
BUILD_CACHE_TEMPLATE = REPO_ROOT / "infra" / "cloud-sandbox" / "build-cache.sh"
PROVISION_HOST_SNIPPET = REPO_ROOT / "infra" / "cloud-sandbox" / "provision-host.sh"

_COLORS = {"red": "31", "green": "32", "yellow": "33", "blue": "34"}


def _colored(color: str, text: str, *, stream: object = sys.stdout) -> str:
    if not hasattr(stream, "isatty") or not stream.isatty():
        return text
    code = _COLORS.get(color, "0")
    return f"\033[{code}m{text}\033[0m"


def _ts() -> str:
    return time.strftime("%H:%M:%S", time.gmtime())


def info(msg: str) -> None:
    print(f"[{_ts()}] {_colored('blue', msg)}")


def success(msg: str) -> None:
    print(f"[{_ts()}] {_colored('green', f'✓ {msg}')}")


def warn(msg: str) -> None:
    print(f"[{_ts()}] {_colored('yellow', f'Warning: {msg}', stream=sys.stderr)}", file=sys.stderr)


def error(msg: str) -> None:
    print(f"[{_ts()}] {_colored('red', f'Error: {msg}', stream=sys.stderr)}", file=sys.stderr)


def fatal(msg: str) -> NoReturn:
    error(msg)
    sys.exit(1)


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env_extra or {})} if env_extra else None
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=capture,
        env=full_env,
    )


def slugify(branch: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", branch.lower().replace("/", "-"))
