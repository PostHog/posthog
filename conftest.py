import gc
import warnings

import pytest

# Test-session boot — plugin imports and importing every collected test module —
# allocates almost exclusively permanent objects, so automatic cyclic GC during that
# phase only adds pauses (seconds on a full-tree CI shard collection). Run the boot
# with GC off, then freeze the survivors into the permanent generation so the
# collector never rescans them during the test phase. Tests themselves run with GC
# enabled as usual. The window normally opens even earlier, in the pytest_boot_gc
# plugin (`-p pytest_boot_gc` in pytest.ini), so that django.setup() — which
# pytest-django runs before conftest files load — sits inside it too; the disable
# here is the fallback for runs that don't load that plugin (e.g. ee/pytest.ini).
gc.disable()


def _end_gc_boot_window() -> None:
    if gc.isenabled():
        return
    # Deliberately no gc.collect() before the freeze: sweeping the boot garbage
    # (including items deselected by pytest-split sharding — measured at ~7k cyclic
    # objects for a 5-way shard of posthog/api/test) costs ~0.5s per invocation but
    # reclaims only ~1MB, so the garbage gets frozen along with the survivors.
    gc.freeze()
    gc.enable()
    # Collect far less often than the default (700, 10, 10): test runs allocate heavily and
    # cyclic garbage is reclaimed fine at these thresholds, while frequent young-gen sweeps
    # over a large frozen heap cost real wall time (~10% of a unit-heavy suite; measured on
    # products/warehouse_sources with peak RSS within 1% of the default thresholds).
    gc.set_threshold(50_000, 20, 20)
    # gc.get_referrers() cannot see referrers in the frozen permanent generation,
    # which turns hypothesis's register_random() liveness check into a false positive
    # for Randoms registered after the freeze (e.g. trio's module-level instance,
    # registered when hypothesis is first imported). Refcounts are unaffected, so the
    # ReferenceError path for real misuse still works; only the warning is spurious.
    warnings.filterwarnings("ignore", message=r"It looks like `register_random` was passed")


def _cache_reverse_rel_identity() -> None:
    # ForeignObjectRel.identity is a plain property that rebuilds a large nested tuple
    # (including make_hashable over limit_choices_to) on every __eq__/__hash__ call.
    # Query compilation over models whose default manager applies .defer()/.only()
    # (Team, User) hashes and compares these rel objects millions of times per test
    # session. Rel objects are immutable once django.setup() has run, so caching the
    # identity tuple and its hash per instance is safe and cuts that cost entirely.
    from functools import cached_property  # noqa: PLC0415 — deferred until pytest_configure

    from django.db.models.fields.reverse_related import (  # noqa: PLC0415 — deferred until pytest_configure
        ForeignObjectRel,
    )

    def walk(klass):
        yield klass
        for sub in klass.__subclasses__():
            yield from walk(sub)

    for klass in walk(ForeignObjectRel):
        prop = klass.__dict__.get("identity")
        if isinstance(prop, property) and prop.fget is not None:
            cached = cached_property(prop.fget)
            cached.__set_name__(klass, "identity")
            klass.identity = cached  # type: ignore[assignment]

    def cached_hash(self) -> int:
        try:
            return self._identity_hash
        except AttributeError:
            self._identity_hash = h = hash(self.identity)
            return h

    ForeignObjectRel.__hash__ = cached_hash  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

    # __eq__ compares the full identity tuples element by element (each element itself a
    # Field with a non-trivial __eq__), and dict probing in select-mask construction calls
    # it millions of times between the same pairs of objects. Rel objects are stable for
    # the life of the process, so memoize results pairwise; keeping a strong ref to the
    # other object means its id() can never be recycled while cached.
    orig_eq = ForeignObjectRel.__eq__

    def cached_eq(self, other):
        if self is other:
            return True
        cache = self.__dict__.get("_eq_cache")
        if cache is None:
            cache = self.__dict__["_eq_cache"] = {}
        entry = cache.get(id(other))
        if entry is None:
            entry = cache[id(other)] = (other, orig_eq(self, other))
        return entry[1]

    # _eq_cache is per-instance and per-session (unbounded), holding strong refs to every
    # object each rel is ever compared with. Bounded by schema size, not test count, so
    # harmless in practice — but don't mistake it for a per-test cache.
    cached_eq.__wrapped__ = orig_eq  # exposes the original for the canary tests
    ForeignObjectRel.__eq__ = cached_eq  # type: ignore[method-assign, assignment]  # ty: ignore[invalid-assignment]


def _cache_select_masks() -> None:
    # Query.get_select_mask() rebuilds the defer/only select-mask dict on every queryset
    # compile. Models whose default manager applies .defer() (Team, User) recompute the
    # identical mask thousands of times per test session, and building it probes dicts
    # keyed by fields/rels with expensive __hash__/__eq__. The result is a pure function
    # of (model meta, defer flag, deferred names) and its only consumer reads it without
    # mutating, so memoize it. Queries with filtered relations keep the original path.
    from django.db.models.sql.query import Query  # noqa: PLC0415 — deferred until pytest_configure

    orig_get_select_mask = Query.get_select_mask
    masks: dict = {}

    def get_select_mask(self):
        field_names, defer = self.deferred_loading
        if not field_names:
            return {}
        if self._filtered_relations:
            return orig_get_select_mask(self)
        key = (self.get_meta(), defer, frozenset(field_names))
        mask = masks.get(key)
        if mask is None:
            mask = masks[key] = orig_get_select_mask(self)
        return mask

    get_select_mask.__wrapped__ = orig_get_select_mask  # exposes the original for the canary tests
    Query.get_select_mask = get_select_mask  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]


def _cache_drf_field_info() -> None:
    # DRF's ModelSerializer.get_fields() calls model_meta.get_field_info(model) on every
    # serializer *instantiation*, re-walking the model's forward and reverse relations each
    # time. The result is static per model class and consumers never mutate it, so cache it.
    from rest_framework.utils import model_meta  # noqa: PLC0415 — deferred until pytest_configure

    orig_get_field_info = model_meta.get_field_info
    infos: dict = {}

    def get_field_info(model):
        key = model if isinstance(model, type) else model.__class__
        info = infos.get(key)
        if info is None:
            info = infos[key] = orig_get_field_info(model)
        return info

    get_field_info.__wrapped__ = orig_get_field_info  # exposes the original for the canary tests
    model_meta.get_field_info = get_field_info  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]


def _cache_url_resolution() -> None:
    # URL resolution walks PostHog's very large nested router linearly on every request
    # (~thousands of pattern match attempts per resolve). Resolution is deterministic per
    # (resolver, path) and URLResolver instances are stable module-level objects, so memoize
    # matches. Keyed weakly by resolver so urlconf overrides (which build new resolvers)
    # can't alias; the per-hit shallow copy keeps callers free to mutate the match/kwargs.
    import weakref  # noqa: PLC0415 — deferred until pytest_configure

    from django.urls import resolvers  # noqa: PLC0415 — deferred until pytest_configure

    orig_resolve = resolvers.URLResolver.resolve
    cache: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    def resolve(self, path):
        by_path = cache.get(self)
        if by_path is None:
            by_path = cache.setdefault(self, {})
        path_str = str(path)
        hit = by_path.get(path_str)
        if hit is None:
            hit = orig_resolve(self, path)
            by_path[path_str] = hit
        # ResolverMatch blocks copy.copy via __reduce_ex__, so clone through __dict__.
        # Copy the kwargs dicts — the attributes consumers realistically mutate — so
        # mutation can't poison the cached original.
        match = object.__new__(type(hit))
        match.__dict__.update(hit.__dict__)
        match.kwargs = dict(hit.kwargs)
        match.captured_kwargs = dict(getattr(hit, "captured_kwargs", None) or {})
        match.extra_kwargs = dict(getattr(hit, "extra_kwargs", None) or {})
        return match

    resolve.__wrapped__ = orig_resolve  # exposes the original for the canary tests
    resolvers.URLResolver.resolve = resolve  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]


def _cheapen_freezegun_module_hash() -> None:
    # Every freeze_time().start() revalidates freezegun's per-module patch cache by
    # hashing each loaded module's attribute list: hash(frozenset(dir(module))) across
    # every module in sys.modules, per freeze. dir() sorts and materializes a list per
    # module, so freeze-heavy suites pay seconds per run for it (2.25M hash calls in a
    # profiled replay-listing run). tuple(module.__dict__) carries the same invalidation
    # signal ~6x cheaper: every module attribute add/delete mutates __dict__ (dir() has
    # no extra visibility for cache purposes — PEP 562 lazy attrs only materialize into
    # __dict__ anyway), and both keys share the same blind spot (rebinding an existing
    # name), so semantics are unchanged. Installed before any freeze so the cache never
    # mixes hash schemes.
    import types  # noqa: PLC0415 — deferred until pytest_configure

    from freezegun import api  # noqa: PLC0415 — deferred until pytest_configure

    def _fast_module_attributes_hash(module: types.ModuleType) -> str:
        try:
            keys_hash = hash(tuple(module.__dict__))
        except (ImportError, TypeError, AttributeError):
            keys_hash = 0
        return f"{id(module)}-{keys_hash}"

    _fast_module_attributes_hash.__wrapped__ = api._get_module_attributes_hash  # type: ignore[attr-defined]
    api._get_module_attributes_hash = _fast_module_attributes_hash  # ty: ignore[invalid-assignment]


def pytest_configure(config) -> None:
    _cache_reverse_rel_identity()
    _cache_select_masks()
    _cache_drf_field_info()
    _cache_url_resolution()
    _cheapen_freezegun_module_hash()


def pytest_collection_finish() -> None:
    _end_gc_boot_window()


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop() -> None:
    # Safety net for processes that never run a local collection (e.g. the
    # pytest-xdist controller): end the window before the test loop starts.
    _end_gc_boot_window()


def pytest_unconfigure() -> None:
    # Frozen objects skip the final cyclic collections of interpreter shutdown, so their
    # finalizers run in the late teardown phase where extension modules may already be
    # gone — observed as exit code 139 (SIGSEGV) on the Temporal CI shards. Restore the
    # default heap state so shutdown behaves exactly as without the boot window.
    gc.unfreeze()


@pytest.fixture(autouse=True)
def _activate_personhog_fake(request):
    """Force all person/group reads through the personhog fake for every test.

    The fake is seeded explicitly by the test helpers in posthog.test.persons
    (create_person, create_group, etc.).  While the fake is active, ORM access to
    persons-DB models raises (PersonsDBORMBlockedError) so nothing can silently
    fall back to the persons DB.

    Tests that exercise the persons DB layer itself (sync, backfill, maintenance
    commands) opt out with ``@pytest.mark.persons_db_direct`` — either on the
    class/function or as a module-level ``pytestmark``.
    """
    if request.node.get_closest_marker("persons_db_direct"):
        yield
        return
    from posthog.personhog_client.fake_client import activate_personhog_fake  # noqa: PLC0415, I001 — lazy import avoids connecting signals before Django is ready

    with activate_personhog_fake():
        yield


@pytest.fixture(autouse=True)
def _clean_persons_db_for_direct_tests(request):
    """Truncate the persons DB before each persons_db_direct test.

    These tests seed the persons DB through off-Django psycopg (posthog.test.persons), which
    commits outside Django's per-test transaction and so is NOT rolled back at teardown. Because
    team ids reset every test (the main DB rolls back), leaked rows from a prior test would bleed
    into the next one's reused team id. Truncating before the test (when no Django persons
    transaction holds locks yet) clears that carryover without risking a TRUNCATE lock hang.
    """
    if not request.node.get_closest_marker("persons_db_direct"):
        yield
        return

    from posthog.persons_db import persons_db_connection  # noqa: PLC0415

    with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename NOT LIKE 'pg_%' AND tablename NOT LIKE '_sqlx_%' AND tablename != '_persons_migrations'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        if tables:
            cursor.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
    yield
