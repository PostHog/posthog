import pytest

from ee.api.agentic_provisioning.views import ALLOWED_PROVISIONING_SCOPES, _validate_scopes


@pytest.mark.parametrize(
    "scopes,expected",
    [
        ([], []),
        (["query:read"], ["query:read"]),
        (["llm_gateway:read", "project:read"], ["llm_gateway:read", "project:read"]),
        (["dashboard:write", "insight:write"], ["dashboard:write", "insight:write"]),
        (["query:read", "made_up_scope"], None),
        (["dashboard:read"], None),
        (["INSIGHT:READ"], None),
        # introspection is not a grantable OAuth scope (RFC 7662 endpoint, not a scope) — should be rejected.
        (["introspection"], None),
    ],
)
def test_validate_scopes(scopes, expected):
    assert _validate_scopes(scopes) == expected


def test_allowlist_covers_wizard_required_scopes():
    wizard_scopes = {
        "user:read",
        "project:read",
        "llm_gateway:read",
        "dashboard:write",
        "insight:write",
        "query:read",
    }
    assert wizard_scopes.issubset(ALLOWED_PROVISIONING_SCOPES)
