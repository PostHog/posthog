"""
Sanity tests for `validate_spec` on AgentRevisionSerializer.

The JSON Schema in `spec_schema.py` is a hand-copied snapshot of the zod
`AgentSpecSchema`. These tests cover the cases that matter for the
authoring flow — known-bad specs that should be rejected before they hit
the DB, and the minimal valid spec that should pass.

Drift against zod is checked the next time someone touches the spec, not
on every test run — the cost of a more aggressive check isn't worth it
for a small surface that moves rarely.
"""

from __future__ import annotations

import pytest

from rest_framework.exceptions import ValidationError

from .serializers import AgentRevisionSerializer

# `auth` lost its top-level default (see spec_schema.py), so it's required on
# every spec. These fixtures focus on other fields, so inject a minimal public
# auth rather than repeat it in each case.
_AUTH = {"modes": [{"type": "public"}]}


def _with_auth(spec: dict) -> dict:
    return {"auth": _AUTH, **spec}


@pytest.mark.parametrize(
    ("name", "spec"),
    [
        ("minimal", {"model": "anthropic/claude-haiku-4-5"}),
        (
            "with_chat_trigger",
            {
                "model": "x",
                "triggers": [{"type": "chat", "config": {"require_auth": False}}],
            },
        ),
        (
            "kitchen_sink",
            {
                "model": "x",
                "triggers": [
                    {"type": "chat", "config": {"require_auth": True}},
                    {"type": "webhook", "config": {"path": "/hook"}},
                ],
                "tools": [{"kind": "native", "id": "@posthog/query"}],
                "skills": [{"id": "research", "path": "skills/research.md"}],
                "entrypoint": "agent.md",
            },
        ),
        # Nested defaults must mirror zod: omitting fields with defaults at
        # any depth is fine. These were the rough edges I hit when I first
        # tried to spec the slack / cron triggers — both have config fields
        # with `.default(...)` in zod that the JSON Schema lists as required.
        (
            "slack_omits_mention_only",
            {
                "model": "x",
                "triggers": [{"type": "slack", "config": {"trusted_workspaces": "*"}}],
            },
        ),
        (
            "cron_omits_timezone",
            {
                "model": "x",
                "triggers": [{"type": "cron", "config": {"schedule": "0 * * * *"}}],
            },
        ),
        (
            "mcp_omits_config",
            {
                "model": "x",
                "triggers": [{"type": "mcp", "config": {}}],
            },
        ),
        # External MCP ref with a mix of bare-string and object tool entries,
        # all distinct names — accepted.
        (
            "external_mcp_unique_tools",
            {
                "model": "x",
                "mcps": [
                    {
                        "kind": "external",
                        "id": "linear",
                        "url": "https://mcp.linear.app/sse",
                        "tools": ["list-issues", {"name": "create-issue", "requires_approval": True}],
                    }
                ],
            },
        ),
        # Registry-pin shapes the freeze pipeline resolves: a skill carrying
        # `from_template` + `alias` (+ optional `version`) alongside the
        # runtime id/path, and a `custom_template` tool ref. Before these
        # were added to the schema, authoring either was rejected.
        (
            "skill_from_template",
            {
                "model": "x",
                "skills": [
                    {
                        "id": "research",
                        "path": "skills/research/SKILL.md",
                        "from_template": "019e7fb7-f4c0-75e2-9055-7c29a5cbb923",
                        "alias": "research",
                        "version": 3,
                    }
                ],
            },
        ),
        (
            "custom_template_tool",
            {
                "model": "x",
                "tools": [
                    {
                        "kind": "custom_template",
                        "from_template": "019e7fb7-f4c0-75e2-9055-7c29a5cbb924",
                        "alias": "stripe_lookup",
                        "version": 4,
                    }
                ],
            },
        ),
    ],
)
def test_validate_spec_accepts_valid_payloads(name: str, spec: dict) -> None:
    AgentRevisionSerializer().validate_spec(_with_auth(spec))


@pytest.mark.parametrize(
    ("name", "spec", "expected_substring"),
    [
        # The exact case we hit today: a spec that looks like an application
        # row (name/description) instead of a runtime config (model).
        ("missing_model", {"name": "Hedgebox Helper"}, "model"),
        # `model` must be a non-empty string. zod uses min(1); JSON Schema
        # mirrors that via minLength.
        ("empty_model", {"model": ""}, "model"),
        # `triggers` must be an array if present, not a string.
        ("triggers_wrong_type", {"model": "x", "triggers": "all"}, "triggers"),
        # Discriminated union: an unknown trigger type doesn't match any of
        # the chat/slack/webhook/cron/mcp variants.
        (
            "unknown_trigger_type",
            {"model": "x", "triggers": [{"type": "carrier_pigeon", "config": {}}]},
            "triggers",
        ),
        # Top-level `additionalProperties: false` should reject extra keys —
        # exactly the `name` / `description` case I tripped earlier.
        ("extra_top_level_key", {"model": "x", "description": "agent"}, "description"),
        # Non-defaulted nested fields must still be rejected when missing —
        # the relaxation only removes required-with-defaults, not all required.
        # jsonschema's `oneOf` error doesn't surface which arm failed for what
        # reason; we just assert the trigger element itself is flagged.
        (
            "slack_missing_trusted_workspaces",
            {"model": "x", "triggers": [{"type": "slack", "config": {"mention_only": False}}]},
            "triggers.0",
        ),
        (
            "cron_missing_schedule",
            {"model": "x", "triggers": [{"type": "cron", "config": {"timezone": "UTC"}}]},
            "triggers.0",
        ),
        # Duplicate tool names in `mcps[].external.tools[]` — JSON Schema can't
        # express this across the string/object union, so the Python-level
        # check mirrors the zod `.refine()`. Bare-string vs bare-string.
        (
            "external_mcp_duplicate_tool_strings",
            {
                "model": "x",
                "mcps": [
                    {
                        "kind": "external",
                        "id": "linear",
                        "url": "https://mcp.linear.app/sse",
                        "tools": ["create-issue", "create-issue"],
                    }
                ],
            },
            "unique names",
        ),
        # Bare-string colliding with an object of the same name — the case
        # JSON Schema's `uniqueItems` would miss entirely.
        (
            "external_mcp_duplicate_tool_string_and_object",
            {
                "model": "x",
                "mcps": [
                    {
                        "kind": "external",
                        "id": "linear",
                        "url": "https://mcp.linear.app/sse",
                        "tools": ["create-issue", {"name": "create-issue", "requires_approval": True}],
                    }
                ],
            },
            "unique names",
        ),
    ],
)
def test_validate_spec_rejects_invalid_payloads(name: str, spec: dict, expected_substring: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AgentRevisionSerializer().validate_spec(_with_auth(spec))
    assert expected_substring in str(exc_info.value)
