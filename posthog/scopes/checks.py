"""Whether held scopes cover required ones: `:write` covers `:read`, legacy fallbacks and the read-only downgrade."""

from collections.abc import Iterable

from . import catalog, exposure


def downgrade_scopes_to_read_only(scope_str: str) -> str:
    """Strip write access from a space-separated OAuth scope string.

    - `<object>:write` becomes `<object>:read`.
    - `*` is the full-access wildcard (see `posthog/permissions.py` — `if "*" in key_scopes`
      short-circuits the scope check, granting read+write). Pass-through would defeat the
      downgrade, so `*` is expanded to every public `*:read` scope.
    - Existing `<object>:read` scopes and OIDC scopes (`openid`, `profile`, `email`) pass through.

    Returns a deduped, space-separated string preserving first-seen order.
    """
    if not scope_str:
        return scope_str
    all_public_read_scopes = [
        f"{obj}:read"
        for obj in catalog.API_SCOPE_OBJECTS
        if obj not in exposure.INTERNAL_API_SCOPE_OBJECTS and obj not in exposure.OAUTH_HIDDEN_SCOPE_OBJECTS
    ]
    expanded: list[str] = []
    for raw in scope_str.split():
        if raw == "*":
            expanded.extend(all_public_read_scopes)
        elif raw.endswith(":write"):
            expanded.append(raw[: -len(":write")] + ":read")
        else:
            expanded.append(raw)
    seen: set[str] = set()
    deduped: list[str] = []
    for s in expanded:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return " ".join(deduped)


def _with_read_halves(scopes: frozenset[str]) -> frozenset[str]:
    return frozenset(scopes | {scope.replace(":write", ":read") for scope in scopes if scope.endswith(":write")})


def scopes_not_covered(held_scopes: Iterable[str], required_scopes: Iterable[str]) -> list[str]:
    """The required scopes that the held scopes do not cover, in the order given. A `:write` scope
    covers the matching `:read`. APIScopePermission and project secret API key issuance share this
    rule, so an issued key cannot get a scope that the issuing credential cannot use. Callers handle
    `*` themselves, because APIScopePermission does not let `*` reach INTERNAL scope objects."""
    covered = _with_read_halves(frozenset(held_scopes))
    return [scope for scope in required_scopes if scope not in covered]


# A new scope object split off a legacy one, mapped to that legacy object. While old keys and tokens
# carry only the legacy scope, a held `<legacy>:<action>` satisfies a required `<new>:<action>`.
# APIScopePermission applies this and records each use, so the entry can go when no caller needs it.
# Project secret API key issuance does not apply it: a key must not get a scope on the strength of a
# legacy one. `hogli build:projections` copies this map to the MCP server, which applies it in `hasScope`.
LEGACY_SCOPE_FALLBACKS: dict[str, str] = {
    # Notes moved from `account:*` to `account_note:*`, so keys and tokens issued before the split keep working.
    "account_note": "account",
    "inbox": "task",
    # Permanent: `hog_flow:write` stays a supported way to set recipient preferences. Keep it on low use.
    "messaging_preference": "hog_flow",
    # Permanent: `hog_flow` stays a supported way to send transactional email and read a send's status.
    "transactional_email": "hog_flow",
}


def scopes_covered_by_legacy_fallback(held_scopes: Iterable[str], missing_scopes: Iterable[str]) -> dict[str, str]:
    """The missing scopes that a legacy scope in LEGACY_SCOPE_FALLBACKS covers, each mapped to that
    legacy scope. The legacy scope follows the same rule as `scopes_not_covered`: `:write` covers `:read`."""
    held = frozenset(held_scopes)
    covered: dict[str, str] = {}
    for scope in missing_scopes:
        scope_object, _, action = scope.partition(":")
        legacy_object = LEGACY_SCOPE_FALLBACKS.get(scope_object)
        if legacy_object is None:
            continue
        legacy_scope = f"{legacy_object}:{action}"
        if not scopes_not_covered(held, [legacy_scope]):
            covered[scope] = legacy_scope
    return covered
