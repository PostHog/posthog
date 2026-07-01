"""
Django-side helpers for `AgentSpec`.

The agent-spec JSON Schema is NOT defined here. The canonical zod
`AgentSpecSchema` (`services/agent-shared/src/spec/spec.ts`) is the single
source of truth; the janitor emits it on demand (`/spec-schema`, surfaced as
the `agent-applications-spec-schema` MCP tool) and the runner parses against
it. Django no longer carries a hand-maintained mirror — keeping a Python copy
in lockstep with zod was a recurring drift hazard, and structural validation
already runs node-side (the explicit `validate` action, freeze, the runner).

What remains here is the per-trigger required-secrets registry, which is a
Django concern (the promote gate reads `encrypted_env`) and has no schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── Per-trigger-type required secrets ──────────────────────────────────────
#
# NOT authored here. `TRIGGER_REQUIRED_SECRETS` is owned by the TS registry
# (`services/agent-shared/src/spec/trigger-secrets.ts`), which is total by
# construction (`Record<TriggerType, …>`). That registry emits the checked-in
# JSON we load below; there is no Python copy to keep in lockstep. This is the
# same move Django already made for the agent-spec schema — a hand-maintained
# Python mirror was a recurring drift hazard. Regenerate the JSON after editing
# the TS registry (a freshness test guards it):
#
#   UPDATE_GENERATED=1 npx vitest run src/spec/trigger-secrets-codegen.test.ts
#
# The slack trigger handler in agent-ingress reads these same keys via the TS
# constants; the freeze / promote gate here rejects revisions whose agent's
# `encrypted_env` is missing a `required` key.

SLACK_SIGNING_SECRET_KEY = "SLACK_SIGNING_SECRET"
SLACK_BOT_TOKEN_KEY = "SLACK_BOT_TOKEN"

_GENERATED_REGISTRY = Path(__file__).parent / "trigger_required_secrets.generated.json"
TRIGGER_REQUIRED_SECRETS: dict[str, list[dict[str, Any]]] = json.loads(_GENERATED_REGISTRY.read_text())


def _auth_mode_secret_requirement(mode: dict[str, Any]) -> dict[str, Any] | None:
    """The `encrypted_env` key an auth mode references, or None. Mirrors the
    `secret_ref` / `issuer_secret_ref` fields on `AuthModeSchema`."""
    mtype = mode.get("type")
    if mtype == "shared_secret":
        key = mode.get("secret_ref")
        if isinstance(key, str) and key:
            header = mode.get("header") or ""
            return {
                "key": key,
                "label": "Webhook shared secret",
                "description": f"Expected value for the `{header}` header. Callers must send this exact secret.",
                "required": True,
            }
    elif mtype == "jwt":
        key = mode.get("issuer_secret_ref")
        if isinstance(key, str) and key:
            return {
                "key": key,
                "label": "JWT signing secret",
                "description": "HMAC secret used to verify inbound JWT signatures for this trigger.",
                "required": True,
            }
    return None


def missing_required_secrets(spec: dict[str, Any], env_map: dict[str, str]) -> list[dict[str, Any]]:
    """Walk `spec.triggers` and return the required-secret entries whose keys
    aren't present in `env_map`. Covers both the per-trigger-type registry
    (`TRIGGER_REQUIRED_SECRETS`) and the per-trigger `auth.modes[]` secret refs
    (`shared_secret.secret_ref`, `jwt.issuer_secret_ref`). Empty list = OK to
    promote. Each entry carries the trigger type under `trigger`.

    Pure / side-effect-free so the same helper can drive both the promote-time
    gate and the "what's still missing?" UI hint."""
    out: list[dict[str, Any]] = []
    triggers = spec.get("triggers") or []
    if not isinstance(triggers, list):
        return out
    seen_keys: set[str] = set()
    seen_unknown: set[str] = set()

    def consider(requirement: dict[str, Any], trigger_type: str) -> None:
        if not requirement.get("required"):
            return
        key = requirement["key"]
        if key in seen_keys:
            return
        seen_keys.add(key)
        if not env_map.get(key):
            out.append({**requirement, "trigger": trigger_type})

    for trigger in triggers:
        if not isinstance(trigger, dict):
            continue
        trigger_type = trigger.get("type")
        if not isinstance(trigger_type, str):
            continue
        requirements = TRIGGER_REQUIRED_SECRETS.get(trigger_type)
        if requirements is None:
            # Fail closed: a type absent from this registry means Django's secret contract
            # drifted behind the zod `TriggerType` enum. Block promote loudly rather than pass
            # with zero required secrets.
            if trigger_type not in seen_unknown:
                seen_unknown.add(trigger_type)
                out.append(
                    {
                        "key": f"<no secret contract for '{trigger_type}' trigger>",
                        "label": "Unregistered trigger type",
                        "description": (
                            f"The '{trigger_type}' trigger has no entry in TRIGGER_REQUIRED_SECRETS; "
                            "add its required-secret contract in spec_schema.py before promoting."
                        ),
                        "required": True,
                        "trigger": trigger_type,
                    }
                )
            continue
        for requirement in requirements:
            consider(requirement, trigger_type)
        auth = trigger.get("auth")
        modes = auth.get("modes") if isinstance(auth, dict) else None
        if isinstance(modes, list):
            for mode in modes:
                if not isinstance(mode, dict):
                    continue
                auth_requirement = _auth_mode_secret_requirement(mode)
                if auth_requirement is not None:
                    consider(auth_requirement, trigger_type)
    return out
