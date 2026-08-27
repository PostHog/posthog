"""Guard: every routed viewset action must resolve to an API scope.

`APIScopePermission` denies a personal API key or OAuth token whenever the action has no
derivable scope (posthog/permissions.py). An action derives a scope through one of three
mechanisms:

    1. a `required_scopes` list on the route (the `@action(..., required_scopes=[...])` kwarg),
    2. a `dangerously_get_required_scopes` method on the viewset, or
    3. the action name appearing in the viewset's read or write action lists
       (`scope_object_read_actions` / `scope_object_write_actions`, default CRUD otherwise).

A custom `@action` that matches none of the three falls through to the denial at
posthog/permissions.py: the endpoint works in the UI but is unreachable from the API, and
nothing reports it until a support ticket arrives weeks later.

This guard freezes the current offenders in a baseline. A new routed action with no derivable
scope fails the test. Give the action a scope through one of the three mechanisms above. Only
when the action is deliberately session-only, regenerate the baseline:

    python posthog/test/repo_invariants/test_api_scope_coverage.py
"""

from pathlib import Path

from parameterized import parameterized

BASELINE_PATH = Path(__file__).parent / "api_scope_coverage_baseline.txt"

READ_DEFAULT = ["list", "retrieve"]
WRITE_DEFAULT = ["create", "update", "partial_update", "patch", "destroy"]


def _action_has_derivable_scope(view: object, action: str, read_default: list[str], write_default: list[str]) -> bool:
    # Mirrors posthog.permissions.ScopeBasePermission._get_required_scopes for the case that
    # matters here: whether the action resolves to any scope at all.
    if getattr(view, "required_scopes", None):
        return True
    if hasattr(view, "dangerously_get_required_scopes"):
        return True

    scope_object = getattr(view, "scope_object", None)
    if not scope_object or scope_object == "INTERNAL":
        # No scope_object means the route is not APIScopePermission-gated. INTERNAL is a
        # programmatic-only boundary that never resolves through this path.
        return True

    read_actions = getattr(view, "scope_object_read_actions", read_default)
    write_actions = getattr(view, "scope_object_write_actions", write_default)
    return action in read_actions or action in write_actions


def collect_offenders() -> set[str]:
    # Imported here, not at module level, so the regeneration entrypoint can call
    # django.setup() first — both imports pull in Django models.
    from posthog.api import router  # noqa: PLC0415
    from posthog.permissions import ScopeBasePermission  # noqa: PLC0415

    read_default = ScopeBasePermission.read_actions
    write_default = ScopeBasePermission.write_actions

    offenders: set[str] = set()
    for pattern in router.urls:
        callback = getattr(pattern, "callback", None)
        viewset_class = getattr(callback, "cls", None)
        actions = getattr(callback, "actions", None)
        if viewset_class is None or actions is None:
            continue

        view = viewset_class()
        # The router stores per-route kwargs (e.g. `required_scopes`) as initkwargs, which
        # `as_view` sets on the view instance. Apply them so the resolution sees the same state.
        for key, value in dict(getattr(callback, "initkwargs", {})).items():
            try:
                setattr(view, key, value)
            except (AttributeError, TypeError):
                continue

        for action in set(actions.values()):
            if not _action_has_derivable_scope(view, action, read_default, write_default):
                offenders.add(f"{viewset_class.__module__}.{viewset_class.__qualname__} {action}")

    return offenders


def read_baseline() -> set[str]:
    return {line.strip() for line in BASELINE_PATH.read_text().splitlines() if line.strip()}


def write_baseline(offenders: set[str]) -> None:
    BASELINE_PATH.write_text("\n".join(sorted(offenders)) + "\n")


class _FakeView:
    def __init__(self, **attrs: object) -> None:
        self.__dict__.update(attrs)


class _FakeViewWithDangerousScopes(_FakeView):
    def dangerously_get_required_scopes(self, request: object, view: object) -> None:
        return None


# Guards the resolver directly: if it ever weakens to always report a scope, the router-wide
# test still passes (its offender set only shrinks), so the guard would silently disable itself.
@parameterized.expand(
    [
        ("no scope object is not gated", _FakeView(), "data_freshness", True),
        ("internal scope never resolves here", _FakeView(scope_object="INTERNAL"), "data_freshness", True),
        ("custom action without a scope", _FakeView(scope_object="annotation"), "data_freshness", False),
        (
            "required_scopes covers the action",
            _FakeView(scope_object="annotation", required_scopes=["annotation:read"]),
            "data_freshness",
            True,
        ),
        (
            "dangerously_get_required_scopes covers the action",
            _FakeViewWithDangerousScopes(scope_object="annotation"),
            "data_freshness",
            True,
        ),
        (
            "action listed in scope_object_read_actions",
            _FakeView(scope_object="annotation", scope_object_read_actions=["list", "retrieve", "data_freshness"]),
            "data_freshness",
            True,
        ),
        ("default read action resolves", _FakeView(scope_object="annotation"), "retrieve", True),
        (
            "standard action dropped from an explicit write list",
            _FakeView(scope_object="annotation", scope_object_write_actions=[]),
            "destroy",
            False,
        ),
    ]
)
def test_action_has_derivable_scope(_name: str, view: object, action: str, expected: bool) -> None:
    assert _action_has_derivable_scope(view, action, READ_DEFAULT, WRITE_DEFAULT) is expected


def test_no_new_actions_without_derivable_scope() -> None:
    offenders = collect_offenders()
    baseline = read_baseline()
    regressions = sorted(offenders - baseline)
    assert not regressions, (
        "These routed actions resolve to no API scope, so APIScopePermission denies every "
        "personal API key and OAuth token — the endpoint works in the UI but is unreachable "
        "from the API. Declare a scope with `@action(..., required_scopes=[...])`, add the "
        "action to the viewset's `scope_object_read_actions` / `scope_object_write_actions`, or "
        "add a `dangerously_get_required_scopes` method. Only if the action is deliberately "
        "session-only, regenerate the baseline: "
        "python posthog/test/repo_invariants/test_api_scope_coverage.py\n" + "\n".join(regressions)
    )


if __name__ == "__main__":
    import django

    django.setup()
    collected = collect_offenders()
    write_baseline(collected)
    print(f"baseline written: {len(collected)} offenders")  # noqa: T201
