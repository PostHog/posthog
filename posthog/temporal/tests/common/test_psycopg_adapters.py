import uuid

from psycopg import postgres
from psycopg.adapt import AdaptersMap, PyFormat
from psycopg.types.uuid import register_default_adapters

from posthog.temporal.common.psycopg_adapters import warm_up_psycopg_adapters


def _fresh_adapters_map() -> AdaptersMap:
    # Mirror psycopg's process-global map right after import: the UUID dumper is registered
    # under its string name ("uuid.UUID"), not yet resolved to the class key.
    m = AdaptersMap(types=postgres.types)
    register_default_adapters(m)
    return m


def test_warm_up_resolves_uuid_dumper_to_class_key():
    m = _fresh_adapters_map()

    # Pre-condition: only the lazy string key exists. First-use resolution rewrites this
    # string key to the class key via a non-atomic pop-then-set, which is the race that
    # crashes concurrent UUID binds on the Temporal worker thread pool.
    assert "uuid.UUID" in m._dumpers[PyFormat.TEXT]
    assert uuid.UUID not in m._dumpers[PyFormat.TEXT]

    warm_up_psycopg_adapters(m)

    # After warmup every format resolves by class, so later lookups take the read-only fast
    # path and never mutate the shared dict.
    for fmt in (PyFormat.AUTO, PyFormat.TEXT, PyFormat.BINARY):
        assert uuid.UUID in m._dumpers[fmt]

    # Idempotent: a second call is a no-op fast-path lookup, not an error.
    warm_up_psycopg_adapters(m)
    assert uuid.UUID in m._dumpers[PyFormat.TEXT]
