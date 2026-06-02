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
                                    "trusted_workspaces": {
                                        "anyOf": [
                                            {"minItems": 1, "type": "array", "items": {"type": "string"}},
                                            {"type": "string", "const": "*"},
                                        ]
                                    },
                                },
                                "required": ["mention_only", "trusted_workspaces"],
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
                            "config": {
                                "type": "object",
                                "properties": {
                                    "schedule": {"type": "string"},
                                    "timezone": {"default": "UTC", "type": "string"},
                                },
                                "required": ["schedule", "timezone"],
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
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "const": "native"},
                            "id": {"type": "string"},
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
                                "maximum": 60000,
                                "default": 5000,
                            },
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
            "items": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "const": "agent"},
                            "slug": {"type": "string"},
                        },
                        "required": ["kind", "slug"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "const": "external"},
                            "url": {"type": "string", "format": "uri"},
                            "auth": {
                                "type": "object",
                                "properties": {"integration": {"type": "string"}},
                                "additionalProperties": False,
                            },
                            "allowlist": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["kind", "url"],
                        "additionalProperties": False,
                    },
                ]
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
            },
            "required": ["max_turns", "max_tool_calls", "max_wall_seconds"],
            "additionalProperties": False,
        },
        "entrypoint": {"default": "agent.md", "type": "string"},
        "auth": {
            # Nested object default removed — Orval's codegen stringifies
            # `[{"type": "public"}]` as `[object Object]` in the generated
            # zod file. The `modes` field has its own leaf default below,
            # which is what actually applies in practice.
            "type": "object",
            "properties": {
                "modes": {
                    # Multi-mode auth — first verifier matching the inbound
                    # request wins. See `AuthModeSchema` in
                    # services/agent-shared/src/spec/spec.ts for the full
                    # contract and the credential-broker design.
                    "default": [{"type": "public"}],
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {"type": {"type": "string", "const": "public"}},
                                "required": ["type"],
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
