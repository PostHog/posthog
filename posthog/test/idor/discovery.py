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
        if not _supports_auto_lookup(cls):
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


def _supports_auto_lookup(cls: type) -> bool:
    """Return True if the viewset's lookup_field can be resolved off a model instance.

    `pk` / `id` always work. Custom names like `short_id`, `kind`, `name`,
    `group_type_index` work as long as the model has a matching attribute.
    Joined attributes like `user__uuid` are rejected — Django ORM exposes
    them only through `__` traversal, not as a single attribute.
    """
    lookup_field = getattr(cls, "lookup_field", "pk")
    lookup_url_kwarg = getattr(cls, "lookup_url_kwarg", None)
    candidate = lookup_url_kwarg or lookup_field
    if "__" in candidate:
        return False
    return True


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
    """True when `instance.<attr_name>` is readable.

    For URL kwargs like `pk` we trust Django; for everything else we require
    the model to declare a field with that name. Properties / methods that
    require complex setup are excluded (they show up as missing fields).
    """
    if attr_name in {"pk", "id"}:
        return True
    try:
        model_cls._meta.get_field(attr_name)
        return True
    except Exception:
        return False


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


def _should_replace(existing: IDORTestCase, candidate: IDORTestCase) -> bool:
    existing_pref = _ROOT_PREFERENCE.get(existing.url.root, 99)
    candidate_pref = _ROOT_PREFERENCE.get(candidate.url.root, 99)
    if candidate_pref < existing_pref:
        return True
    if candidate_pref > existing_pref:
        return False
    # Same root; prefer fewer intermediate parents (shallower path)
    return len(candidate.url.intermediate_parents) < len(existing.url.intermediate_parents)
