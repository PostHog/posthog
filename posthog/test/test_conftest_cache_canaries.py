# Canary tests for the test-harness monkeypatches in the repo-root conftest.py.
#
# Each patch caches a Django/DRF internal on the assumption that it is a pure function
# of immutable inputs *in the currently pinned Django/DRF version*. If an upgrade
# invalidates one of those assumptions, the harness would silently diverge from stock
# behavior and surface as unrelated flakes with nothing pointing at conftest.py.
# These tests compare each patched callable against its unpatched original (exposed
# as `__wrapped__` at the patch site) for a representative case, so the divergence
# fails loudly here instead.
#
# If one of these fails after a Django/DRF upgrade: re-verify the assumption named in
# the corresponding `_cache_*` function in conftest.py, and if it no longer holds,
# delete that patch — do not "fix" the test.

from django.db.models.fields.reverse_related import ForeignObjectRel
from django.db.models.sql.query import Query
from django.urls import resolvers

from rest_framework.utils import model_meta

from posthog.models import Team


def _unpatched(patched):
    orig = getattr(patched, "__wrapped__", None)
    assert orig is not None, (
        f"{patched} does not expose its unpatched original via __wrapped__ — "
        "was the conftest.py patch changed without updating the canaries?"
    )
    return orig


def test_select_mask_cache_matches_unpatched_django():
    # Assumption: get_select_mask is a pure function of (model meta, defer flag,
    # deferred names) and consumers never mutate the returned mask.
    query = Team.objects.all().query  # Team's default manager applies .defer()
    field_names, _ = query.deferred_loading
    assert field_names, "Team no longer defers fields — pick another model for this canary"
    patched = query.get_select_mask()
    fresh = _unpatched(Query.get_select_mask)(query)
    assert patched == fresh
    # Repeated calls serve the memoized mask and must stay equal to a fresh compute.
    assert query.get_select_mask() == fresh


def test_rel_identity_cache_matches_unpatched_django():
    # Assumption: ForeignObjectRel objects are immutable after django.setup(), so
    # identity/__hash__ can be cached per instance and __eq__ memoized pairwise.
    rels = [f for f in Team._meta.get_fields() if isinstance(f, ForeignObjectRel)]
    assert len(rels) >= 2, "Team has no reverse relations — pick another model for this canary"
    orig_eq = _unpatched(ForeignObjectRel.__eq__)
    for rel in rels[:5]:
        # identity is an undocumented Django internal, absent from django-stubs.
        cached_identity = rel.identity  # type: ignore[attr-defined] # via the cached_property installed by conftest
        cached_hash = hash(rel)
        # Recompute from the original property fget (cached_property.func). Subclass fgets
        # (ManyToOneRel etc.) internally do `super().identity`, which routes through the
        # base class's cached_property and leaves the partial base tuple in the instance
        # dict — so clear the instance cache before and after to keep the rel pristine.
        descriptor = type(rel).identity  # type: ignore[attr-defined]
        rel.__dict__.pop("identity", None)
        try:
            fresh_identity = descriptor.func(rel)
        finally:
            # Always restore: rels are process-global, and a partial tuple left behind
            # would corrupt hash/eq for every later test in the same worker.
            rel.__dict__.pop("identity", None)
        assert cached_identity == fresh_identity
        assert cached_hash == hash(fresh_identity)
    # Compare a same-class pair — across classes the original __eq__ returns
    # NotImplemented rather than a bool.
    by_type: dict[type, list[ForeignObjectRel]] = {}
    for rel in rels:
        by_type.setdefault(type(rel), []).append(rel)
    pair = next((group for group in by_type.values() if len(group) >= 2), None)
    assert pair is not None, "no two Team rels share a class — pick another model for this canary"
    a, b = pair[0], pair[1]
    assert (a == b) == bool(orig_eq(a, b))
    assert (a == a) == bool(orig_eq(a, a))


def test_drf_field_info_cache_matches_unpatched_drf():
    # Assumption: get_field_info is static per model class and consumers never mutate it.
    patched = model_meta.get_field_info(Team)
    fresh = _unpatched(model_meta.get_field_info)(Team)
    assert patched == fresh


def test_url_resolution_cache_matches_unpatched_django():
    # Assumption: URLResolver.resolve is deterministic per (resolver, path), and the
    # __dict__-based ResolverMatch clone reproduces everything consumers read.
    resolver = resolvers.get_resolver()
    path = "/api/users/@me/"
    patched = resolver.resolve(path)
    fresh = _unpatched(resolvers.URLResolver.resolve)(resolver, path)
    for attr in (
        "func",
        "args",
        "kwargs",
        "url_name",
        "route",
        "app_names",
        "namespaces",
        "captured_kwargs",
        "extra_kwargs",
        "view_name",
    ):
        assert getattr(patched, attr) == getattr(fresh, attr), f"ResolverMatch.{attr} diverged from unpatched resolve"
    # A second resolve serves the cached match — mutating one clone's kwargs must not
    # leak into the next (the cross-test cache-poisoning hazard).
    patched.kwargs["canary"] = True
    again = resolver.resolve(path)
    assert "canary" not in again.kwargs
