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

from typing import Any

# ── Per-trigger-type required secrets ──────────────────────────────────────
#
# Mirrors `services/agent-shared/src/spec/trigger-secrets.ts` for the
# Django-side validation path. Keep the two in lockstep — the slack trigger
# handler in agent-ingress reads `SLACK_SIGNING_SECRET_KEY` and the freeze /
# promote gate here rejects revisions whose agent's `encrypted_env` is missing
# the same key.

SLACK_SIGNING_SECRET_KEY = "SLACK_SIGNING_SECRET"
SLACK_BOT_TOKEN_KEY = "SLACK_BOT_TOKEN"

TRIGGER_REQUIRED_SECRETS: dict[str, list[dict[str, Any]]] = {
    "chat": [],
    "webhook": [],
    "cron": [],
    "mcp": [],
    "slack": [
        {
            "key": SLACK_SIGNING_SECRET_KEY,
            "label": "Slack signing secret",
            "description": (
                "Your Slack app's signing secret. Find it under Settings → Basic Information → "
                "Signing Secret. Required to verify inbound Slack event signatures."
            ),
            "required": True,
        },
        {
            "key": SLACK_BOT_TOKEN_KEY,
            "label": "Slack bot user OAuth token",
            "description": (
                "Your Slack app's bot token (starts with `xoxb-`). Find it under Settings → "
                "Install App → Bot User OAuth Token after installing the app to your workspace. "
                "Used by native slack tools to call the Slack API."
            ),
            "required": True,
        },
    ],
}


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
        for requirement in TRIGGER_REQUIRED_SECRETS.get(trigger_type, []):
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
