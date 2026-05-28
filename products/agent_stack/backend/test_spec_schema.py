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
    ],
)
def test_validate_spec_accepts_valid_payloads(name: str, spec: dict) -> None:
    AgentRevisionSerializer().validate_spec(spec)


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
    ],
)
def test_validate_spec_rejects_invalid_payloads(name: str, spec: dict, expected_substring: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AgentRevisionSerializer().validate_spec(spec)
    assert expected_substring in str(exc_info.value)
