"""
JSON Schema for `AgentSpec`, copy-pasted from the canonical zod schema at
`services/agent-shared/src/spec/spec.ts` (`AgentSpecSchema`).

The zod schema is the source of truth — every other consumer (janitor at read
time, runner at session start, this file at write time) must agree on its
shape. We copy rather than codegen because the zod surface is small enough
that drift is caught loudly by `test_spec_schema.py` (which re-emits the zod
schema and diffs it against the embedded copy).

## When zod changes

1. Run the regen one-liner from `test_spec_schema.test_no_drift_vs_zod` (the
   test prints it on failure).
2. Replace `_AGENT_SPEC_JSON_SCHEMA_RAW` below with the new output.
3. Re-run the test; it should pass.

## Why two schemas

zod's `.default([...])` makes a field optional at parse time — you can omit
`triggers` and zod fills it in. JSON Schema's `required` doesn't respect
defaults; if `triggers` is in `required`, every Django write needs to send
the full empty list. To preserve zod semantics on the Django side, the
`_relax_required_for_defaults` pass strips fields with `default` from the
top-level `required` array.

- `AGENT_SPEC_JSON_SCHEMA` — full shape, used for OpenAPI annotation so the
  MCP tool surface advertises every field plus its default.
- `AGENT_SPEC_JSON_SCHEMA_FOR_WRITE` — relaxed required list, used for
  Django `validate_spec` so the same `{"model": "x"}` that zod accepts also
  passes Django.
"""

from __future__ import annotations

import copy
from typing import Any

# Shared `approval_policy` block — referenced from every tool variant that
# can be approval-gated (native + custom + MCP entries). Mirror
# `ApprovalPolicySchema` in services/agent-shared/src/spec/spec.ts.
_APPROVAL_POLICY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approvers": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "enum": ["team_admins", "session_principal"]},
            "default": ["team_admins"],
        },
        "allow_edit": {"type": "boolean", "default": False},
        "ttl_ms": {
            "type": "integer",
            "minimum": 60000,
            "maximum": 7 * 24 * 60 * 60 * 1000,
            "default": 24 * 60 * 60 * 1000,
        },
        "allow_agent_approver": {"type": "boolean", "default": False},
    },
    "additionalProperties": False,
}

_AGENT_SPEC_JSON_SCHEMA_RAW: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "model": {"type": "string", "minLength": 1},
        "triggers": {
            "default": [],
            "type": "array",
            "items": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "slack"},
                            "config": {
                                "type": "object",
                                "properties": {
                                    "channel_id": {"type": "string"},
                                    "mention_only": {"default": False, "type": "boolean"},
                                    "auto_resume_threads": {"default": False, "type": "boolean"},
                                    "ack_reaction": {"type": "string"},
                                    "trusted_workspaces": {
                                        "anyOf": [
                                            {"minItems": 1, "type": "array", "items": {"type": "string"}},
                                            {"type": "string", "const": "*"},
                                        ]
                                    },
                                },
                                "required": ["mention_only", "auto_resume_threads", "trusted_workspaces"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["type", "config"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "webhook"},
                            "config": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "secret": {"type": "string"},
                                },
                                "required": ["path"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["type", "config"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "cron"},
                            # Mirror of the node cron config (services/agent-shared
                            # spec.ts, added by the cron scheduler PR #61028). The
                            # upstream Django mirror lagged at {schedule, timezone};
                            # synced here so cron-triggered agents validate.
                            "config": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "minLength": 1},
                                    "schedule": {"type": "string", "minLength": 1},
                                    "timezone": {"default": "UTC", "type": "string"},
                                    "prompt": {"type": "string", "minLength": 1, "maxLength": 4096},
                                    "external_key": {"type": "string"},
                                    "catch_up": {
                                        "enum": ["all", "most_recent", "skip"],
                                        "default": "most_recent",
                                    },
                                    "max_catch_up_age_seconds": {
                                        "type": "integer",
                                        "minimum": 1,
                                        "maximum": 604800,
                                        "default": 3600,
                                    },
                                },
                                "required": ["name", "schedule", "prompt"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["type", "config"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "chat"},
                            "config": {
                                "type": "object",
                                "properties": {"require_auth": {"default": True, "type": "boolean"}},
                                "required": ["require_auth"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["type", "config"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "mcp"},
                            "config": {
                                "default": {},
                                "type": "object",
                                "properties": {},
                                "additionalProperties": False,
                            },
                        },
                        "required": ["type", "config"],
                        "additionalProperties": False,
                    },
                ]
            },
        },
        "tools": {
            "default": [],
            "type": "array",
            "items": {
                "oneOf": [
                    {
                        # Native + custom tool variants accept the same
                        # inline approval-gating fields as MCP tool
                        # entries (below) — see `ToolRefSchema` in
                        # services/agent-shared/src/spec/spec.ts. Mirror
                        # any changes there.
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "const": "native"},
                            "id": {"type": "string"},
                            "requires_approval": {"type": "boolean", "default": False},
                            "approval_policy": _APPROVAL_POLICY_JSON_SCHEMA,
                        },
                        "required": ["kind", "id"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "const": "custom"},
                            "id": {"type": "string"},
                            "path": {"type": "string"},
                            "requires_approval": {"type": "boolean", "default": False},
                            "approval_policy": _APPROVAL_POLICY_JSON_SCHEMA,
                        },
                        "required": ["kind", "id", "path"],
                        "additionalProperties": False,
                    },
                    {
                        # Registry-pinned custom tool — draft-only shape.
                        # Freeze resolves `from_template` at `version`, writes
                        # `tools/<alias>/…`, and reshapes this into the
                        # `custom` variant above before the runner sees it.
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "const": "custom_template"},
                            "from_template": {"type": "string"},
                            "alias": {"type": "string"},
                            "version": {"type": "integer", "minimum": 0},
                        },
                        "required": ["kind", "from_template", "alias"],
                        "additionalProperties": False,
                    },
                    {
                        # Client-fulfilled tool — implementation lives in the
                        # connecting client (browser dock, IDE MCP host), not
                        # in the runner. See `AgentSpecSchema.tools.client`
                        # in services/agent-shared/src/spec/spec.ts for the
                        # full contract + dispatch model.
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "const": "client"},
                            "id": {"type": "string", "minLength": 1},
                            "description": {"type": "string", "minLength": 1},
                            "args_schema": {"type": "object", "default": {}},
                            "required": {"type": "boolean", "default": False},
                            "timeout_ms": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 600000,
                                "default": 5000,
                            },
                            "interactive": {"type": "boolean", "default": False},
                        },
                        "required": ["kind", "id", "description"],
                        "additionalProperties": False,
                    },
                ]
            },
        },
        "mcps": {
            "default": [],
            "type": "array",
            # Single flat shape — third-party MCP server reachable over HTTP.
            # The `kind: 'agent'` agent-to-agent variant was removed; see
            # `docs/agent-platform/plans/agent-as-mcp-server.md` for re-add.
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "url": {"type": "string", "format": "uri"},
                    "auth": {
                        "type": "object",
                        "properties": {"integration": {"type": "string"}},
                        "additionalProperties": False,
                    },
                    "secrets": {
                        "default": [],
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    # Author-supplied request headers stamped on every outgoing
                    # MCP request. Values may reference `${NAME}` from
                    # `secrets[]`; the runner substitutes the plaintext value
                    # before opening the MCP client. Same substitution shape as
                    # `@posthog/http-request`'s `headers` — the parallel is
                    # intentional. Use for the bring-your-own-token case
                    # (paste a PAT once, reference it as `${TOKEN}` in
                    # `Authorization: 'Bearer ${TOKEN}'`).
                    "headers": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    # Per-tool selection + approval gating. Bare string
                    # = inclusion only (was allowlist[] pre-PR-7);
                    # object form adds requires_approval +
                    # approval_policy. See `McpToolEntrySchema` in
                    # services/agent-shared/src/spec/spec.ts.
                    "tools": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string", "minLength": 1},
                                {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string", "minLength": 1},
                                        "requires_approval": {"type": "boolean", "default": False},
                                        "approval_policy": {
                                            "type": "object",
                                            "properties": {
                                                "approvers": {
                                                    "type": "array",
                                                    "minItems": 1,
                                                    "items": {
                                                        "type": "string",
                                                        "enum": ["team_admins", "session_principal"],
                                                    },
                                                    "default": ["team_admins"],
                                                },
                                                "allow_edit": {"type": "boolean", "default": False},
                                                "ttl_ms": {
                                                    "type": "integer",
                                                    "minimum": 60000,
                                                    "maximum": 7 * 24 * 60 * 60 * 1000,
                                                    "default": 24 * 60 * 60 * 1000,
                                                },
                                                "allow_agent_approver": {
                                                    "type": "boolean",
                                                    "default": False,
                                                },
                                            },
                                            "additionalProperties": False,
                                        },
                                    },
                                    "required": ["name"],
                                    "additionalProperties": False,
                                },
                            ],
                        },
                    },
                },
                "required": ["id", "url"],
                "additionalProperties": False,
            },
        },
        "skills": {
            "default": [],
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "path": {"type": "string"},
                    "description": {"type": "string"},
                    # Registry lineage for a skill pinned from a template.
                    # Present on a draft spec; freeze resolves `from_template`,
                    # assembles `skills/<alias>/SKILL.md`, and stamps id/path.
                    "from_template": {"type": "string"},
                    "alias": {"type": "string"},
                    "version": {"type": "integer", "minimum": 0},
                },
                "required": ["id", "path"],
                "additionalProperties": False,
            },
        },
        "integrations": {"default": [], "type": "array", "items": {"type": "string"}},
        "secrets": {"default": [], "type": "array", "items": {"type": "string"}},
        "limits": {
            "default": {"max_turns": 50, "max_tool_calls": 200, "max_wall_seconds": 900},
            "type": "object",
            "properties": {
                "max_turns": {"default": 50, "type": "integer", "exclusiveMinimum": 0, "maximum": 9007199254740991},
                "max_tool_calls": {
                    "default": 200,
                    "type": "integer",
                    "exclusiveMinimum": 0,
                    "maximum": 9007199254740991,
                },
                "max_wall_seconds": {
                    "default": 900,
                    "type": "integer",
                    "exclusiveMinimum": 0,
                    "maximum": 9007199254740991,
                },
                "max_output_tokens": {
                    "type": "integer",
                    "exclusiveMinimum": 0,
                    "maximum": 200000,
                },
            },
            "required": ["max_turns", "max_tool_calls", "max_wall_seconds"],
            "additionalProperties": False,
        },
        "entrypoint": {"default": "agent.md", "type": "string"},
        "auth": {
            # No defaults at this level or below — Orval emits the default
            # value as a plain TS literal whose inferred type widens
            # `{type: 'public'}` to `{type: string}`, which then fails to
            # satisfy the generated discriminated-union zod schema. The
            # runtime default still applies via the node-side
            # `AuthConfigSchema.default({ modes: [{ type: 'posthog_internal' }] })`
            # in services/agent-shared/src/spec/spec.ts — closed by default.
            # Public is opt-in and requires `acknowledge_public_exposure: true`.
            "type": "object",
            "properties": {
                "modes": {
                    # Multi-mode auth — first verifier matching the inbound
                    # request wins. See `AuthModeSchema` in
                    # services/agent-shared/src/spec/spec.ts for the full
                    # contract and the credential-broker design.
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {
                                # Public exposure is intentionally opt-in and noisy.
                                # `acknowledge_public_exposure: true` is required to
                                # surface the choice in UIs and to gate AI-authored
                                # specs against accidentally opening agents to the
                                # internet. Mirrors `AuthModeSchema` in
                                # services/agent-shared/src/spec/spec.ts.
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "const": "public"},
                                    "acknowledge_public_exposure": {"type": "boolean", "const": True},
                                },
                                "required": ["type", "acknowledge_public_exposure"],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "const": "oauth"},
                                    "issuer": {"type": "string", "minLength": 1},
                                    "scopes": {
                                        "default": [],
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["type", "issuer"],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {"type": {"type": "string", "const": "pat"}},
                                "required": ["type"],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "const": "jwt"},
                                    "issuer_secret_ref": {"type": "string", "minLength": 1},
                                },
                                "required": ["type", "issuer_secret_ref"],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "const": "shared_secret"},
                                    "header": {"type": "string", "minLength": 1},
                                },
                                "required": ["type", "header"],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {"type": {"type": "string", "const": "posthog_internal"}},
                                "required": ["type"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                },
            },
            "additionalProperties": False,
        },
        "reasoning": {"type": "string", "enum": ["minimal", "low", "medium", "high", "xhigh"]},
    },
    "required": [
        "model",
        "triggers",
        "tools",
        "mcps",
        "skills",
        "integrations",
        "secrets",
        "limits",
        "entrypoint",
        "auth",
    ],
    "additionalProperties": False,
}


def _relax_required_for_defaults(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively strip `required` entries whose property schema has a default.

    Mirrors zod's `.default()` semantics: a field with a default is optional
    at parse time. JSON Schema's `required` doesn't infer this from `default`,
    so we transform it here. The walk covers every object node reachable via
    `properties`, `items`, `oneOf`/`anyOf`/`allOf`, `additionalProperties`,
    and `propertyNames` — i.e. every nested schema zod emits, including the
    discriminated trigger union (`triggers[].config.mention_only`,
    `triggers[].config.timezone`, …).
    """
    out = copy.deepcopy(schema)
    _relax_node(out)
    return out


def _relax_node(node: Any) -> None:
    if not isinstance(node, dict):
        return

    # Strip required entries whose property is defaulted.
    props = node.get("properties")
    required = node.get("required")
    if isinstance(props, dict) and isinstance(required, list):
        node["required"] = [r for r in required if not (isinstance(props.get(r), dict) and "default" in props[r])]

    # Recurse through every schema-bearing child.
    if isinstance(props, dict):
        for v in props.values():
            _relax_node(v)
    items = node.get("items")
    if isinstance(items, dict):
        _relax_node(items)
    elif isinstance(items, list):
        for v in items:
            _relax_node(v)
    for key in ("oneOf", "anyOf", "allOf"):
        sub = node.get(key)
        if isinstance(sub, list):
            for v in sub:
                _relax_node(v)
    add_props = node.get("additionalProperties")
    if isinstance(add_props, dict):
        _relax_node(add_props)
    prop_names = node.get("propertyNames")
    if isinstance(prop_names, dict):
        _relax_node(prop_names)


AGENT_SPEC_JSON_SCHEMA: dict[str, Any] = _AGENT_SPEC_JSON_SCHEMA_RAW
AGENT_SPEC_JSON_SCHEMA_FOR_WRITE: dict[str, Any] = _relax_required_for_defaults(_AGENT_SPEC_JSON_SCHEMA_RAW)


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


def missing_required_secrets(spec: dict[str, Any], env_map: dict[str, str]) -> list[dict[str, Any]]:
    """Walk `spec.triggers` and return the `TriggerSecretRequirement` entries
    whose `required: True` keys aren't present in `env_map`. Empty list = OK
    to promote. Each entry comes back with the trigger type tucked in under
    `trigger` so the caller can render a per-trigger error message.

    Pure / side-effect-free so the same helper can drive both the promote-time
    gate and a future "what's still missing?" UI hint."""
    out: list[dict[str, Any]] = []
    triggers = spec.get("triggers") or []
    if not isinstance(triggers, list):
        return out
    seen_keys: set[str] = set()
    for trigger in triggers:
        if not isinstance(trigger, dict):
            continue
        trigger_type = trigger.get("type")
        if not isinstance(trigger_type, str):
            continue
        for requirement in TRIGGER_REQUIRED_SECRETS.get(trigger_type, []):
            if not requirement.get("required"):
                continue
            key = requirement["key"]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if not env_map.get(key):
                out.append({**requirement, "trigger": trigger_type})
    return out
