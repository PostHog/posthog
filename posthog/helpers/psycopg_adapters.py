"""Resolve psycopg's name-registered dumpers before any worker thread runs a query.

psycopg registers the dumpers for several stdlib types by dotted name instead of by class —
``uuid.UUID``, ``datetime.datetime``, ``decimal.Decimal`` and the ``ipaddress`` types all
arrive as string keys. The first lookup of each has to swap that name key for the class key,
and in psycopg 3.2.4 the swap is ``d = dmap[scls] = dmap.pop(fqn)``
(``psycopg/_adapters_map.py``), which is not atomic. A second thread that reaches the same
lookup between the pop and the insert finds neither key and raises ``ProgrammingError:
cannot adapt type 'UUID' using placeholder '%t'``, blaming whatever application code happened
to be running there. Upstream fixed this in 3.3.2 (psycopg issue #1230).

The exposure is wider than one lookup per process: Django builds a fresh adapters map from the
global one for every new connection, so a cold global map re-runs the swap — and the race —
on each connection. Doing the lookups here, single-threaded at app startup, leaves the global
map keyed by class, and every map later copied from it inherits that.

Remove this once the psycopg pin reaches 3.3.2 or later.
"""

import sys
from typing import Any

import psycopg
import structlog
from psycopg.adapt import AdaptersMap

logger = structlog.get_logger(__name__)


def _resolve(fqn: str) -> type | None:
    """Resolve a dotted name to a class, without importing any module that isn't loaded yet.

    psycopg registers optional third-party types by name too (``numpy.int8`` and friends), and
    importing those at startup to warm them would cost far more than the race it avoids. A type
    whose module is absent also has no instances yet, so no thread can be dumping one.
    """
    parts = fqn.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module = sys.modules.get(".".join(parts[:split]))
        if module is None:
            continue
        obj: Any = module
        for attr in parts[split:]:
            obj = getattr(obj, attr, None)
            if obj is None:
                break
        if isinstance(obj, type):
            return obj
    return None


def warm(adapters: AdaptersMap | None = None) -> None:
    """Swap name-keyed dumpers to class keys, on the global map by default. Idempotent."""
    if adapters is None:
        adapters = psycopg.adapters
    try:
        dumpers = adapters._dumpers
    except AttributeError:
        # Private attribute. A psycopg version that drops it is past the 3.3.2 fix that makes
        # this warm-up unnecessary, so there is nothing to fall back to.
        return

    for fmt, by_key in dumpers.items():
        # get_dumper rewrites the mapping we are reading, so take the names first. Iterating
        # it live raises "dictionary keys changed during iteration" and breaks startup.
        for fqn in [key for key in by_key if isinstance(key, str)]:
            cls = _resolve(fqn)
            if cls is None:
                continue
            try:
                adapters.get_dumper(cls, fmt)
            except Exception:
                # Every process runs this at boot, so a driver that refuses one name must
                # cost the warm-up for that name, not the process.
                logger.warning("psycopg_adapter_warm_failed", fqn=fqn, format=str(fmt))
