#!/usr/bin/env python3
"""Generate OAUTH_SCOPES_SUPPORTED for the MCP protected-resource metadata.

The MCP server publishes RFC 9728 protected-resource metadata at
`/.well-known/oauth-protected-resource`. Spec-compliant clients (e.g. Claude
Code) read `scopes_supported` from there and pass every entry to the
authorization server's `/oauth/authorize`. If the resource list contains a
scope the AS does not recognize, sign-in fails with `invalid_scope`.

The AS metadata is computed dynamically by Django from
`posthog.scopes.get_scope_descriptions()`, plus the OIDC trio handled by
django-oauth-toolkit. To keep the resource list in lockstep, this script
generates `services/mcp/src/lib/oauth-scopes.generated.ts` from the same
function, so both lists derive from one source of truth.

Run via hogli: `hogli build:openapi-mcp-scopes` (also runs as part of
`build:openapi`). See `common/hogli/manifest.yaml`.
"""
# ruff: noqa: T201

from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCOPES_PY = REPO_ROOT / "posthog" / "scopes.py"
OUTPUT_TS = REPO_ROOT / "services" / "mcp" / "src" / "lib" / "oauth-scopes.generated.ts"

# OIDC scopes are added by django-oauth-toolkit's OIDC layer and appear in the
# AS metadata alongside the resource scopes. They are not in
# get_scope_descriptions(), so we add them here to match what the AS actually
# advertises.
OIDC_SCOPES: tuple[str, ...] = ("openid", "profile", "email")


def _load_scopes_module():
    """Import posthog/scopes.py without triggering posthog/__init__.py.

    posthog/__init__.py imports Celery and pulls in Django settings, which
    requires a running database. scopes.py itself only depends on `typing`,
    so we can load it directly via importlib.
    """
    spec = importlib.util.spec_from_file_location("_posthog_scopes", SCOPES_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SCOPES_PY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_posthog_scopes"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    scopes_module = _load_scopes_module()
    resource_scopes = sorted(scopes_module.get_scope_descriptions().keys())
    all_scopes = list(OIDC_SCOPES) + resource_scopes

    # oxfmt enforces single quotes in this repo. json.dumps emits double, so
    # format manually. Scope names are simple snake_case identifiers + colons,
    # never need escaping, but assert that to fail loudly if a scope ever does.
    for s in all_scopes:
        assert "'" not in s and "\\" not in s, f"unexpected character in scope name: {s!r}"
    body = ",\n".join(f"    '{s}'" for s in all_scopes)
    output = (
        "// AUTO-GENERATED. Do not edit.\n"
        "// Source: posthog/scopes.py via bin/build-mcp-oauth-scopes.py.\n"
        "// Regenerate with `hogli build:openapi-mcp-scopes`.\n"
        "//\n"
        "// This list is published as `scopes_supported` in the MCP protected-resource\n"
        "// metadata (RFC 9728). It MUST be a subset of the authorization server's\n"
        "// `scopes_supported`, otherwise spec-compliant OAuth clients fail with\n"
        "// `invalid_scope`. Both lists derive from `get_scope_descriptions()` to keep\n"
        "// them in lockstep.\n"
        "\n"
        "export const OAUTH_SCOPES_SUPPORTED = [\n"
        f"{body},\n"
        "] as const\n"
        "\n"
        "export type OAuthScope = (typeof OAUTH_SCOPES_SUPPORTED)[number]\n"
    )

    OUTPUT_TS.parent.mkdir(parents=True, exist_ok=True)
    existing = OUTPUT_TS.read_text() if OUTPUT_TS.exists() else None
    if existing != output:
        OUTPUT_TS.write_text(output)
        print(f"wrote {OUTPUT_TS} ({len(all_scopes)} scopes)")
    else:
        print(f"{OUTPUT_TS} already up to date ({len(all_scopes)} scopes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
