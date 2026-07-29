"""The canvas platform contract, loaded from the builder package's manifest.

manifest.json is the single source of truth shared by the Node builder
(build.mjs), this Python validator/build service, and the artifact origin's
CSP. The desktop app asserts its own copy against the same file in a contract
test, so a drift in pinned dependencies or limits fails loudly instead of
diverging silently.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings

CANVAS_BUILDER_DIR = Path(settings.CANVAS_BUILDER_DIR)


@lru_cache(maxsize=1)
def platform_contract() -> dict[str, Any]:
    return json.loads((CANVAS_BUILDER_DIR / "manifest.json").read_text())


def platform_dependencies() -> dict[str, str]:
    """Pinned name → exact version of every platform-supported dependency."""
    return {name: entry["version"] for name, entry in platform_contract()["dependencies"].items()}


def allowed_import_specifiers() -> frozenset[str]:
    return frozenset(platform_contract()["allowedImportSpecifiers"])


def artifact_csp() -> str:
    return platform_contract()["csp"]


def contract_limits() -> dict[str, int]:
    return platform_contract()["limits"]


def canvas_sdk_version() -> str:
    return platform_contract()["canvasSdkVersion"]
