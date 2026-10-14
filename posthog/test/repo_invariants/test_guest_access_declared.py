from collections.abc import Iterator
from pathlib import Path

from django.urls import URLPattern, URLResolver, get_resolver

from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import GuestPermission

BASELINE = Path(__file__).with_name("guest_access_exempt_views_baseline.txt")


def _url_patterns(patterns: list[URLPattern | URLResolver]) -> Iterator[URLPattern]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _url_patterns(pattern.url_patterns)
        else:
            yield pattern


def _views_outside_the_mixin() -> dict[str, type[APIView]]:
    views: dict[str, type[APIView]] = {}
    for pattern in _url_patterns(get_resolver().url_patterns):
        view = getattr(pattern.callback, "cls", None) or getattr(pattern.callback, "view_class", None)
        if not isinstance(view, type) or not issubclass(view, APIView) or issubclass(view, TeamAndOrgViewSetMixin):
            continue
        views[f"{view.__module__}.{view.__qualname__}"] = view
    return views


def _exempt_views() -> set[str]:
    return {line.split("#")[0].strip() for line in BASELINE.read_text().splitlines()} - {""}


def test_views_outside_the_team_mixin_declare_guest_access() -> None:
    views = _views_outside_the_mixin()
    undeclared = sorted(
        name
        for name, view in views.items()
        if name not in _exempt_views() and GuestPermission not in getattr(view, "permission_classes", ())
    )
    assert not undeclared, (
        "A guest session could reach these views. Add GuestPermission to permission_classes, or add the view to "
        f"{BASELINE.name} with the reason a guest cannot reach it:\n  " + "\n  ".join(undeclared)
    )


def test_guest_access_baseline_has_no_stale_views() -> None:
    stale = sorted(_exempt_views() - set(_views_outside_the_mixin()))
    assert not stale, f"Remove these views from {BASELINE.name}:\n  " + "\n  ".join(stale)
