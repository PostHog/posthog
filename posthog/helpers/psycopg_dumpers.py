"""Resolve psycopg's lazily-registered dumpers once, before any thread can race on them.

Importing ``uuid`` and ``decimal`` is slow, so psycopg registers dumpers for a few types
under their fully qualified *name* instead of the class — see
``psycopg.types.uuid.register_default_adapters``. The name is swapped for the class on
first use, inside ``AdaptersMap.get_dumper``::

    d = dmap[scls] = dmap.pop(fqn)

That pops the name before inserting the class, so for a moment the dumper is registered
under neither key, and the lookup is unlocked. The map is process-wide in practice —
Django hands every connection one ``lru_cache``d template — so a thread adapting a
``UUID`` inside that window fails with ``cannot adapt type 'UUID' using placeholder
'%t'``, even though the dumper is registered. It is a first-use race only: once the class
key lands, ``get_dumper`` takes its fast path for the life of the process.

Resolving each name here, single-threaded at startup, closes the window. Ordering matters
— this has to run before anything opens a connection, because Django's template copies
whatever the global map holds at the time it is built.

psycopg 3.3.2 reordered the two operations so one key is always present. Once we're on
that version this module can go.
"""

import uuid
import decimal
import datetime
import ipaddress

import structlog

logger = structlog.get_logger(__name__)

# The stdlib types psycopg registers by name. numpy's are left out on purpose: importing
# numpy at startup costs far more than the race it would close, and nothing adapts numpy
# scalars as query params on the threaded paths.
LAZILY_REGISTERED_TYPES: tuple[type, ...] = (
    uuid.UUID,
    decimal.Decimal,
    datetime.date,
    datetime.time,
    datetime.datetime,
    datetime.timedelta,
    ipaddress.IPv4Address,
    ipaddress.IPv6Address,
    ipaddress.IPv4Interface,
    ipaddress.IPv6Interface,
    ipaddress.IPv4Network,
    ipaddress.IPv6Network,
)


def prewarm_lazy_dumpers() -> None:
    from psycopg import postgres  # noqa: PLC0415 — keeps the heavy dep off the import path
    from psycopg.adapt import PyFormat  # noqa: PLC0415

    for cls in LAZILY_REGISTERED_TYPES:
        for fmt in PyFormat:
            try:
                postgres.adapters.get_dumper(cls, fmt)
            except Exception:
                # A type psycopg no longer registers for this format is not worth failing
                # startup over — the worst case is the pre-existing race for that type.
                logger.warning("psycopg_dumper_prewarm_failure", type=cls.__qualname__, format=fmt.name)
