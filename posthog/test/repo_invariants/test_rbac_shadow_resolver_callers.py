from pathlib import Path

RESOLVER_NAMES = ("resolve_object_access", "resolve_resource_access")
ALLOWED = {Path("posthog/rbac/user_access_control.py")}
SCANNED_ROOTS = ("posthog", "ee", "products")


def test_shadow_resolvers_have_no_callers_outside_their_module():
    # The most-specific resolvers are WIP shadow code (RFC 557): until the migration flips,
    # enforcement and display must keep using the legacy methods. A new caller anywhere else is
    # almost certainly a mistake — use get_user_access_level / check_access_level_for_object /
    # access_level_for_resource instead, or extend ALLOWED deliberately in a migration PR.
    repo_root = Path(__file__).resolve().parents[3]
    offenders = []
    for root in SCANNED_ROOTS:
        for path in (repo_root / root).rglob("*.py"):
            relative = path.relative_to(repo_root)
            parts = set(relative.parts)
            if relative in ALLOWED or "test" in parts or "tests" in parts or "migrations" in parts:
                continue
            content = path.read_text(errors="ignore")
            if any(name in content for name in RESOLVER_NAMES):
                offenders.append(str(relative))

    assert not offenders, (
        f"These files reference the WIP most-specific resolvers: {offenders}. "
        "They are not enforced yet — call get_user_access_level / access_level_for_resource instead, "
        "or extend ALLOWED here as part of the RFC 557 cutover."
    )
