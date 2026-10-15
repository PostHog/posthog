from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

from django.urls import URLPattern, URLResolver, get_resolver

from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.guest_access import GuestState
from posthog.permissions import GuestPermission

BASELINE = Path(__file__).with_name("guest_reachable_actions_baseline.txt")


def _url_patterns(patterns: list[URLPattern | URLResolver]) -> Iterator[URLPattern]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _url_patterns(pattern.url_patterns)
        else:
            yield pattern


def _guest_reachable_actions() -> set[str]:
    organization = SimpleNamespace(id="organization", is_feature_available=lambda feature: True)
    state = GuestState(is_guest=True, organization=organization, enforced=True)  # type: ignore[arg-type]
    reachable: set[str] = set()
    for pattern in _url_patterns(get_resolver().url_patterns):
        view_class = getattr(pattern.callback, "cls", None)
        if not isinstance(view_class, type) or not issubclass(view_class, APIView):
            continue
        guarded = issubclass(view_class, TeamAndOrgViewSetMixin) or GuestPermission in getattr(
            view_class, "permission_classes", ()
        )
        if not guarded:
            continue
        actions = getattr(pattern.callback, "actions", None) or {}
        for action in set(actions.values()):
            view = SimpleNamespace(
                guest_allowed_actions=getattr(view_class, "guest_allowed_actions", frozenset()), action=action
            )
            request = SimpleNamespace(user=None, _guest_state=state)
            if GuestPermission().has_permission(request, view):  # type: ignore[arg-type]
                reachable.add(f"{view_class.__module__}.{view_class.__qualname__}.{action}")
    return reachable


def test_guest_reachable_actions_match_the_reviewed_baseline() -> None:
    reachable = _guest_reachable_actions()
    reviewed = {line.strip() for line in BASELINE.read_text().splitlines() if line.strip() and not line.startswith("#")}
    added = sorted(reachable - reviewed)
    assert not added, (
        "Guests can now reach these view actions. Check that each one shows a guest only what a grant allows, "
        f"then add it to {BASELINE.name}:\n  " + "\n  ".join(added)
    )
    removed = sorted(reviewed - reachable)
    assert not removed, f"Guests can no longer reach these view actions. Remove them from {BASELINE.name}:\n  " + (
        "\n  ".join(removed)
    )
