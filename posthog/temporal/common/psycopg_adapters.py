"""Warm up psycopg3's lazily-resolved type adapters before concurrent DB access.

psycopg3 registers some dumpers by fully-qualified name rather than by class (e.g.
``adapters.register_dumper("uuid.UUID", UUIDDumper)``) so the type doesn't have to be
imported up front. The first time a value of that type is adapted, ``AdaptersMap.get_dumper``
rewrites the registration from the string key to the class key:

    d = dmap[scls] = dmap.pop(fqn)

That pop-then-set is two separate operations on a dict that connections share by reference
(child adapter maps shallow-copy the global ``psycopg.adapters`` inner dicts until a
copy-on-write). Between the pop and the set the dict holds neither the string key nor the
class key, so another thread copying or reading it in that window ends up without a dumper
and the next bind of that type raises ``cannot adapt type 'UUID' using placeholder '%t'``.

Web and Celery workers are process-based and don't hit this, but Temporal activities run
their ORM queries on a shared ``thread_sensitive=False`` thread pool (see ``posthog.sync``),
so several worker threads open connections and adapt UUIDs concurrently — exactly the race
above. Resolving the adapters once, single-threaded, at worker boot leaves the class key
permanently in place, so every later lookup takes the read-only fast path and never mutates
the shared dict.
"""

from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from psycopg.adapt import AdaptersMap

logger = structlog.get_logger(__name__)


def warm_up_psycopg_adapters(adapters_map: Optional["AdaptersMap"] = None) -> None:
    """Force psycopg3 to resolve its lazily-registered adapters on the main thread.

    Resolves against psycopg's process-global adapters map by default; ``adapters_map`` is an
    override for tests. Idempotent and best-effort: any failure (psycopg2 backend, internal API
    drift) is logged and swallowed rather than blocking worker startup.
    """
    try:
        import uuid

        from psycopg import adapters as global_adapters
        from psycopg.adapt import PyFormat
    except ImportError:
        # psycopg3 isn't the active driver (e.g. psycopg2) — nothing to warm up.
        return

    target = adapters_map if adapters_map is not None else global_adapters

    # UUID is the type that actually bit us: Django binds it as a raw ``uuid.UUID`` object
    # (``has_native_uuid_field``), and every organization/team/etc. primary key lookup dumps one.
    for fmt in (PyFormat.AUTO, PyFormat.TEXT, PyFormat.BINARY):
        try:
            target.get_dumper(uuid.UUID, fmt)
        except Exception:
            logger.warning("psycopg_adapter_warmup_failed", type="uuid.UUID", format=str(fmt))
