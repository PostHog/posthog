from pathlib import Path

RESOLVER_NAMES = ("resolve_most_specific_object_access", "resolve_most_specific_resource_access")
ALLOWED = {Path("products/access_control/backend/facade/user_access_control.py")}
SCANNED_ROOTS = ("posthog", "ee", "products")


def test_shadow_resolvers_have_no_callers_outside_their_module():
    # The most-specific resolvers are shadow code. Until the migration completes,
    # enforcement and display must use the enforced methods: get_user_access_level,
    # check_access_level_for_object, access_level_for_resource. A caller anywhere else is
    # almost certainly a mistake. Extend ALLOWED only in a migration PR.
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
        "or extend ALLOWED here as part of the migration cutover."
    )
