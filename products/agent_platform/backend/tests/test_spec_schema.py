"""
Tests for `AgentRevisionSerializer.validate_spec` + the trigger-secrets helper.

Structural spec validation is the janitor's job now (the zod `AgentSpecSchema`,
parsed at the explicit `validate` action, at freeze, and by the runner) — Django
no longer carries a JSON Schema mirror, so there are no shape-rejection cases
here. What `validate_spec` still owns is the cross-field MCP-tool-name
uniqueness check (which JSON Schema can't express across the string/object
union) and pinning server-derived `skills`. We also cover `missing_required_secrets`.
"""

from __future__ import annotations

import pytest

from rest_framework.exceptions import ValidationError

from ..logic.spec_schema import SLACK_BOT_TOKEN_KEY, SLACK_SIGNING_SECRET_KEY, missing_required_secrets
from ..presentation.serializers import AgentRevisionSerializer, AgentSpecField

# Declarative triggers carry a per-trigger auth block; give them a minimal
# public one so these fixtures can focus on the field under test.
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
        ("empty", {}),
        # Unique MCP tool names (bare string + object form) — accepted.
        (
            "unique_mcp_tools",
            {
                "mcps": [
                    {
                        "id": "linear",
                        "url": "https://mcp.linear.app/sse",
                        "tools": ["list-issues", {"name": "create-issue", "requires_approval": True}],
                    }
                ],
            },
        ),
    ],
)
def test_validate_spec_accepts(name: str, spec: dict) -> None:
    # validate_spec no longer does structural schema validation (that runs
    # node-side); it should accept any spec whose MCP tool names are unique.
    AgentRevisionSerializer().validate_spec(_with_auth(spec))


@pytest.mark.parametrize(
    ("name", "spec"),
    [
        # Bare-string duplicate.
        (
            "duplicate_tool_strings",
            {
                "mcps": [
                    {"id": "linear", "url": "https://mcp.linear.app/sse", "tools": ["create-issue", "create-issue"]}
                ],
            },
        ),
        # Bare-string colliding with an object of the same name — the case
        # JSON Schema's uniqueItems would miss; the serializer enforces it.
        (
            "duplicate_tool_string_and_object",
            {
                "mcps": [
                    {
                        "id": "linear",
                        "url": "https://mcp.linear.app/sse",
                        "tools": ["create-issue", {"name": "create-issue", "requires_approval": True}],
                    }
                ],
            },
        ),
    ],
)
def test_validate_spec_rejects_duplicate_mcp_tool_names(name: str, spec: dict) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AgentRevisionSerializer().validate_spec(_with_auth(spec))
    assert "unique names" in str(exc_info.value)


_SLACK_SPEC = {
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
    spec = {"triggers": [{"type": "chat", "config": {}}]}
    assert missing_required_secrets(spec, {}) == []


# AgentSpecField coerces a stringified-JSON-object spec back to an object. The MCP
# write tools expose `spec` as an opaque arg, so an authoring model sometimes
# passes the whole spec as a JSON string; stored verbatim it's the characters of a
# string and the janitor rejects it (`invalid_request`).


def test_agent_spec_field_coerces_stringified_object() -> None:
    field = AgentSpecField()
    assert field.to_internal_value('{"models": {"mode": "auto"}}') == {"models": {"mode": "auto"}}
    # A real object passes through untouched.
    assert field.to_internal_value({"models": {"mode": "auto"}}) == {"models": {"mode": "auto"}}


@pytest.mark.parametrize("bad", ["not json at all", "[1, 2, 3]", '"a string"', "42"])
def test_agent_spec_field_rejects_non_object_string(bad: str) -> None:
    # Non-JSON, or JSON that isn't an object, is rejected with a clear message
    # rather than stored as a string that later fails freeze.
    with pytest.raises(ValidationError):
        AgentSpecField().to_internal_value(bad)
