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

import json
from pathlib import Path

import pytest

import jsonschema
from rest_framework.exceptions import ValidationError

from ..logic.spec_schema import (
    AGENT_SPEC_JSON_SCHEMA_FOR_WRITE,
    SLACK_BOT_TOKEN_KEY,
    SLACK_SIGNING_SECRET_KEY,
    missing_required_secrets,
)
from ..presentation.serializers import AgentRevisionSerializer

# Auth is per-trigger now (no top-level spec.auth). These fixtures focus on
# other fields, so give every declarative trigger a minimal public auth block
# rather than repeat it in each case. Public exposure carries the explicit ack
# field per AuthModeSchema in services/agent-shared/src/spec/spec.ts.
_PUBLIC_AUTH = {"modes": [{"type": "public", "acknowledge_public_exposure": True}]}


def _with_auth(spec: dict) -> dict:
    triggers = spec.get("triggers")
    if not isinstance(triggers, list):
        return spec
    patched = [
        {**t, "auth": _PUBLIC_AUTH}
        if isinstance(t, dict) and t.get("type") in ("webhook", "chat", "mcp") and "auth" not in t
        else t
        for t in triggers
    ]
    return {**spec, "triggers": patched}


@pytest.mark.parametrize(
    ("name", "spec"),
    [
        ("minimal", {"model": "anthropic/claude-haiku-4-5"}),
        (
            "with_chat_trigger",
            {
                "model": "x",
                "triggers": [{"type": "chat", "config": {}}],
            },
        ),
        (
            "kitchen_sink",
            {
                "model": "x",
                "triggers": [
                    {"type": "chat", "config": {}},
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
                "triggers": [
                    {"type": "cron", "config": {"name": "hourly", "schedule": "0 * * * *", "prompt": "run it"}}
                ],
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
                        "id": "linear",
                        "url": "https://mcp.linear.app/sse",
                        "tools": ["list-issues", {"name": "create-issue", "requires_approval": True}],
                    }
                ],
            },
        ),
        # BYO bearer token: author drops a PAT into spec.secrets, references
        # it from mcps[].headers. Mirrors @posthog/http-request's shape; the
        # runner walks `headers` and substitutes `${NAME}` at session start.
        (
            "external_mcp_byo_headers_with_secret",
            {
                "model": "x",
                "secrets": ["GITHUB_TOKEN"],
                "mcps": [
                    {
                        "id": "github",
                        "url": "https://api.githubcopilot.com/mcp",
                        "secrets": ["GITHUB_TOKEN"],
                        "headers": {
                            "Authorization": "Bearer ${GITHUB_TOKEN}",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
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
        # max_output_tokens is optional; runner picks a reasoning-aware default.
        (
            "limits_max_output_tokens",
            {"model": "x", "limits": {"max_output_tokens": 16384}},
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
                        "id": "linear",
                        "url": "https://mcp.linear.app/sse",
                        "tools": ["create-issue", {"name": "create-issue", "requires_approval": True}],
                    }
                ],
            },
            "unique names",
        ),
        # The exact drift that poisoned the cron sweep: a cron trigger without
        # the now-required `prompt` (or `name`). The node schema rejects these
        # at freeze; the Django mirror must reject them at write so a poisoned
        # spec never reaches the DB in the first place.
        (
            "cron_missing_prompt",
            {"model": "x", "triggers": [{"type": "cron", "config": {"name": "sweep", "schedule": "0 9 * * *"}}]},
            "triggers.0",
        ),
        (
            "cron_missing_name",
            {"model": "x", "triggers": [{"type": "cron", "config": {"schedule": "0 9 * * *", "prompt": "go"}}]},
            "triggers.0",
        ),
    ],
)
def test_validate_spec_rejects_invalid_payloads(name: str, spec: dict, expected_substring: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AgentRevisionSerializer().validate_spec(_with_auth(spec))
    assert expected_substring in str(exc_info.value)


_SLACK_SPEC = {
    "model": "x",
    "triggers": [{"type": "slack", "config": {"trusted_workspaces": "*"}}],
}


@pytest.mark.parametrize(
    ("name", "env", "expected_missing_keys"),
    [
        ("none_set", {}, {SLACK_SIGNING_SECRET_KEY, SLACK_BOT_TOKEN_KEY}),
        ("only_signing_set", {SLACK_SIGNING_SECRET_KEY: "shh"}, {SLACK_BOT_TOKEN_KEY}),
        ("only_bot_set", {SLACK_BOT_TOKEN_KEY: "xoxb-abc"}, {SLACK_SIGNING_SECRET_KEY}),
        ("both_set", {SLACK_SIGNING_SECRET_KEY: "shh", SLACK_BOT_TOKEN_KEY: "xoxb-abc"}, set()),
        (
            "blank_treated_as_missing",
            {SLACK_SIGNING_SECRET_KEY: "", SLACK_BOT_TOKEN_KEY: ""},
            {SLACK_SIGNING_SECRET_KEY, SLACK_BOT_TOKEN_KEY},
        ),
    ],
)
def test_missing_required_secrets_for_slack_trigger(name: str, env: dict, expected_missing_keys: set) -> None:
    missing = missing_required_secrets(_SLACK_SPEC, env)
    assert {entry["key"] for entry in missing} == expected_missing_keys
    for entry in missing:
        assert entry["trigger"] == "slack"
        assert entry["required"] is True


def test_missing_required_secrets_skips_triggers_without_requirements() -> None:
    spec = {"model": "x", "triggers": [{"type": "chat", "config": {}}]}
    assert missing_required_secrets(spec, {}) == []


# Every shipped example bundle must validate against the write schema exactly
# as authored. This is the guard against the drift class that bit us: a field
# added to the zod schema (e.g. `allow_direct_messages`, `resume`) but not
# mirrored here would let an example carry it while the platform silently
# rejects/drops it. The example seeder no longer maintains its own allowlist —
# this schema is the single gate — so a missing mirror now fails here, loudly.
_EXAMPLES_DIR = Path(__file__).parents[2] / "services" / "agent-tests" / "src" / "examples"
_EXAMPLE_SPECS = sorted(p for p in _EXAMPLES_DIR.glob("*/spec.json"))


@pytest.mark.parametrize("spec_file", _EXAMPLE_SPECS, ids=lambda p: p.parent.name)
def test_example_bundles_validate_against_write_schema(spec_file: Path) -> None:
    jsonschema.validate(json.loads(spec_file.read_text()), AGENT_SPEC_JSON_SCHEMA_FOR_WRITE)
