import uuid
import decimal
import datetime

from django.test import SimpleTestCase

import psycopg
from parameterized import parameterized
from psycopg.adapt import AdaptersMap, PyFormat

from posthog.helpers.psycopg_adapters import _resolve, warm

# The stdlib types psycopg registers by dotted name, so each needs a key swap on first lookup.
RACED_TYPES = [(uuid.UUID,), (datetime.datetime,), (decimal.Decimal,)]


def _fqn(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _cold_map(cls: type) -> AdaptersMap:
    """A private adapters map keyed the way psycopg ships it: by dotted name, not by class."""
    adapters = AdaptersMap(template=psycopg.adapters)
    for fmt in PyFormat:
        by_key = dict(psycopg.adapters._dumpers[fmt])
        if cls in by_key:
            by_key[_fqn(cls)] = by_key.pop(cls)
        adapters._dumpers[fmt] = by_key
        adapters._own_dumpers[fmt] = True
    return adapters


class TestPsycopgAdapters(SimpleTestCase):
    @parameterized.expand(RACED_TYPES)
    def test_warming_leaves_no_name_key_to_swap(self, cls: type) -> None:
        # A name key surviving the warm-up is exactly what lets two threads race the driver's
        # non-atomic `dmap[scls] = dmap.pop(fqn)` and raise "cannot adapt type".
        adapters = _cold_map(cls)
        warm(adapters)

        for fmt in PyFormat:
            assert _fqn(cls) not in adapters._dumpers[fmt]
            assert adapters.get_dumper(cls, fmt) is not None

    @parameterized.expand(RACED_TYPES)
    def test_warming_the_global_map_covers_connections_made_later(self, cls: type) -> None:
        # Django templates a fresh adapters map off the global one per connection, so the
        # global map is the one that has to be warm before worker threads start.
        warm()

        assert _fqn(cls) not in psycopg.adapters._dumpers[PyFormat.AUTO]

    def test_resolve_skips_types_whose_module_is_not_imported(self) -> None:
        # psycopg registers optional third-party dumpers by name too; resolving those by
        # importing the module would pull the dependency into every process at startup.
        assert _resolve("posthog_not_a_real_module.SomeType") is None
