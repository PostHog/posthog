import pytest

from psycopg import postgres
from psycopg.adapt import AdaptersMap, PyFormat

from posthog.helpers.psycopg_dumpers import LAZILY_REGISTERED_TYPES, prewarm_lazy_dumpers


def _lazy_keys(adapters: AdaptersMap) -> set[str]:
    return {key for fmt in PyFormat for key in adapters._dumpers[fmt] if isinstance(key, str)}


class TestPrewarmLazyDumpers:
    @pytest.mark.parametrize("cls", LAZILY_REGISTERED_TYPES, ids=lambda cls: cls.__qualname__)
    def test_resolves_type_for_every_format(self, cls: type) -> None:
        # Put the dumper back under its fully qualified name — the state psycopg ships in and
        # the only state the race exists in. django.setup() has already run the prewarm by the
        # time tests execute, so without this the assertions would pass vacuously.
        fqn = f"{cls.__module__}.{cls.__qualname__}"
        for fmt in PyFormat:
            dumpers = postgres.adapters._dumpers[fmt]
            dumper = dumpers.pop(cls, None) or dumpers.get(fqn)
            if dumper is not None:
                dumpers[fqn] = dumper

        prewarm_lazy_dumpers()

        # Keyed by class in every format means get_dumper takes its fast path and never re-runs
        # the unlocked name-to-class swap a concurrent thread can fall into.
        for fmt in PyFormat:
            assert cls in postgres.adapters._dumpers[fmt]

    def test_covers_every_lazily_registered_type_except_numpy(self) -> None:
        # Built from psycopg's own defaults rather than the live global map, which other tests
        # resolve entries out of as a side effect of querying.
        pristine = AdaptersMap(types=postgres.types)
        postgres.register_default_adapters(pristine)

        uncovered = _lazy_keys(pristine) - {f"{cls.__module__}.{cls.__qualname__}" for cls in LAZILY_REGISTERED_TYPES}

        # numpy's dumpers are deliberately skipped. Anything else here is a type psycopg
        # registers lazily that LAZILY_REGISTERED_TYPES needs to cover.
        assert {key for key in uncovered if not key.startswith("numpy.")} == set()
