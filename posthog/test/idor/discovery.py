"""
Discover tenant-scoped viewsets registered on `posthog.api.router`.

The discovery walks `router.urls` once at module import time, classifies
each viewset, and produces an `IDORTestCase` per unique tenant-scoped
viewset with a detail endpoint.

Viewsets registered at multiple URLs (e.g. grandfathered under both
`/projects/:team_id/` and `/environments/:team_id/`) are deduplicated;
we pick the canonical URL in this order:

  1. `/environments/` for team-scoped viewsets (new canonical form)
  2. `/projects/`     for project-scoped viewsets
  3. `/organizations/` for organization-scoped viewsets

This module is intentionally pure (no DB access, no test client) so it
can be imported both by the integration test and by the CI coverage
check script.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import models

from posthog.test.idor.skip_list import IDOR_TEST_SKIP_LIST
from posthog.test.idor.url_structure import URLStructure, parse_url_pattern


@dataclass(frozen=True)
class IDORTestCase:
    """One auto-testable tenant-scoped detail endpoint."""

    viewset_cls: type
    model_cls: type[models.Model]
    url: URLStructure

    @property
    def name(self) -> str:
        return self.viewset_cls.__name__


# Priority order for deduping viewsets registered under multiple roots
_ROOT_PREFERENCE = {"environments": 0, "projects": 1, "organizations": 2}


def discover_idor_test_cases() -> list[IDORTestCase]:
    """Walk `posthog.api.router.urls` and return one IDORTestCase per
    unique tenant-scoped viewset with a detail endpoint."""
    # Imports deferred so this module can be imported without Django setup
    # (e.g. by the URL-structure unit tests or pyright)
    from posthog.api import router
    from posthog.api.routing import TeamAndOrgViewSetMixin

    best_by_viewset: dict[type, IDORTestCase] = {}

    for url_pattern in router.urls:
        callback = getattr(url_pattern, "callback", None)
        cls: Optional[type] = getattr(callback, "cls", None)
        if cls is None:
            continue
        if not issubclass(cls, TeamAndOrgViewSetMixin):
            continue
        if cls.__name__ in IDOR_TEST_SKIP_LIST:
            continue

        model_cls = _infer_model(cls)
        if model_cls is None:
            continue

        structure = parse_url_pattern(str(url_pattern.pattern))
        if structure is None:
            continue
        # The URL's pk kwarg must align with the viewset's `lookup_field` /
        # `lookup_url_kwarg`. Mismatches mean the URL belongs to a custom
        # action that takes a sub-resource id (e.g. `sharing/passwords/<password_id>`)
        # rather than the standard retrieve route — those need hand-written tests.
        if not _url_kwarg_matches_lookup(cls, structure.pk_kwarg):
            continue
        # If the URL kwarg isn't `pk`/`id`, the model must expose an attribute
        # with that name so we can read the lookup value off an auto-built
        # instance. `short_id`, `name`, `kind` etc. all work; `user__uuid`
        # (a joined attribute) doesn't.
        if not _model_has_lookup_attr(model_cls, structure.pk_kwarg):
            continue

        case = IDORTestCase(viewset_cls=cls, model_cls=model_cls, url=structure)
        existing = best_by_viewset.get(cls)
        if existing is None or _should_replace(existing, case):
            best_by_viewset[cls] = case

    return sorted(best_by_viewset.values(), key=lambda c: c.name)


def _url_kwarg_matches_lookup(cls: type, url_kwarg: str) -> bool:
    """Confirm the URL's pk kwarg is the viewset's standard lookup kwarg.

    DRF resolves the detail object via `lookup_url_kwarg` (falling back to
    `lookup_field`) read from `kwargs`. If the URL's pk kwarg doesn't match
    either, we're looking at a custom action URL with a sub-resource id —
    not the standard retrieve route — and we can't auto-test it.
    """
    lookup_field = getattr(cls, "lookup_field", "pk")
    lookup_url_kwarg = getattr(cls, "lookup_url_kwarg", None)
    expected = lookup_url_kwarg or lookup_field
    # Treat `pk` and `id` as interchangeable since DRF auto-routes both.
    if {expected, url_kwarg} <= {"pk", "id"}:
        return True
    return expected == url_kwarg


def _model_has_lookup_attr(model_cls: type[models.Model], attr_name: str) -> bool:
    """True when `attr_name` resolves to a readable attribute on `model_cls`.

    Supports Django-style joined attributes like `user__uuid` by walking each
    `__` segment as an FK and validating the terminal segment is a field on
    the leaf model. `pk` / `id` always work. Properties / methods that
    require complex setup are excluded (they show up as missing fields).
    """
    if attr_name in {"pk", "id"}:
        return True
    segments = attr_name.split("__")
    current: type[models.Model] = model_cls
    for index, segment in enumerate(segments):
        try:
            field = current._meta.get_field(segment)
        except Exception:
            return False
        is_last = index == len(segments) - 1
        if is_last:
            return True
        related = getattr(field, "related_model", None)
        if not (isinstance(related, type) and issubclass(related, models.Model)):
            return False
        current = related
    return True


def _infer_model(cls: type) -> Optional[type[models.Model]]:
    """Find the Model class for a DRF viewset, trying queryset first then serializer."""
    qs = getattr(cls, "queryset", None)
    if qs is not None:
        model = getattr(qs, "model", None)
        if model is not None:
            return model
    serializer_cls = getattr(cls, "serializer_class", None)
    if serializer_cls is not None:
        meta = getattr(serializer_cls, "Meta", None)
        if meta is not None:
            model = getattr(meta, "model", None)
            if model is not None:
                return model
    return None


# Action contexts probed by `iter_serializer_classes_for`. Order is stable so
# that callers iterating the result get a predictable serializer order.
_PROBE_CONTEXTS: tuple[tuple[str, str], ...] = (
    ("create", "POST"),
    ("update", "PUT"),
    ("partial_update", "PATCH"),
    ("retrieve", "GET"),
    ("list", "GET"),
)


def iter_serializer_classes_for(viewset_cls: type) -> list[type]:
    """Return every serializer class a viewset uses, including runtime dispatch.

    A viewset's class-level `serializer_class` attribute is the static fast
    path. Some viewsets override `get_serializer_class()` to dispatch on
    `self.request.method` / `self.action` (e.g. `SurveyViewSet` returns a
    write-only serializer for POST/PATCH and a richer serializer for GET).
    Without probing those methods, FK discovery silently misses every field
    declared only on the write-side serializer — which is exactly where
    cross-tenant injection attacks land.

    Strategy: probe each writable action context with a synthetic instance.
    Defensive try/except so a viewset whose `get_serializer_class()` reaches
    into request internals (auth, headers) doesn't break discovery — falling
    back to the static serializer in the worst case.

    Returns a stable-ordered, deduplicated list keyed by class identity.
    """
    seen: set[type] = set()
    out: list[type] = []

    static = getattr(viewset_cls, "serializer_class", None)
    if static is not None:
        seen.add(static)
        out.append(static)

    for action_name, method in _PROBE_CONTEXTS:
        try:
            instance = viewset_cls()
            instance.action = action_name  # type: ignore[attr-defined]
            instance.request = type(  # type: ignore[attr-defined]
                "FakeRequest",
                (),
                {"method": method, "user": None, "data": {}, "query_params": {}},
            )()
            instance.format_kwarg = None  # type: ignore[attr-defined]
            cls = instance.get_serializer_class()
        except Exception:
            continue
        if cls is None or cls in seen:
            continue
        seen.add(cls)
        out.append(cls)

    return out


def _should_replace(existing: IDORTestCase, candidate: IDORTestCase) -> bool:
    existing_pref = _ROOT_PREFERENCE.get(existing.url.root, 99)
    candidate_pref = _ROOT_PREFERENCE.get(candidate.url.root, 99)
    if candidate_pref < existing_pref:
        return True
    if candidate_pref > existing_pref:
        return False
    # Same root; prefer fewer intermediate parents (shallower path)
    return len(candidate.url.intermediate_parents) < len(existing.url.intermediate_parents)
