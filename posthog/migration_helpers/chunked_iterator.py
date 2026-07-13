from collections.abc import Iterator
from typing import Any

from django.db.models import QuerySet


def chunked_queryset_iterator(queryset: QuerySet, chunk_size: int = 1000) -> Iterator[Any]:
    """Stream a queryset in primary-key-ordered chunks without a server-side cursor.

    Django's ``QuerySet.iterator()`` streams rows through a named server-side cursor
    (psycopg issues ``DECLARE ... CURSOR`` then ``FETCH``). Behind a transaction-pooling
    connection — PgBouncer, or a Postgres-wire proxy that lacks the ``pg_cursors`` view —
    the ``DECLARE`` and the later ``FETCH`` / ``CLOSE`` can land on different backend
    sessions, so the cursor is gone by the time psycopg fetches from or closes it. In a
    migration this surfaces as ``Table not found: pg_cursors`` chained to
    ``Portal "_django_curs_..." not found``, and it fires whenever a pooler sits in front
    of Postgres without ``DISABLE_SERVER_SIDE_CURSORS`` (``USING_PGBOUNCER``) set.

    This helper keyset-paginates by primary key instead: each chunk is an independent
    ``... WHERE pk > last ORDER BY pk LIMIT n`` query that completes on a single session,
    so it is safe on any connection regardless of that setting. Use it in data migrations
    in place of ``queryset.iterator(chunk_size=...)`` when iterating model instances.

    Rows are read once each. Mutating a row so it no longer matches the queryset's filter
    is safe: paging advances strictly by ``pk``, so a processed row is never revisited and
    an unprocessed row is never skipped — matching the stable-snapshot behavior migrations
    relied on from ``iterator()``. Any ``order_by`` on the incoming queryset is replaced by
    primary-key ordering.

    Only model-instance querysets are supported (it reads ``instance.pk``). For
    ``.values()`` / ``.values_list()`` reads, collect the bounded result with ``list(...)``,
    which also avoids the server-side cursor.
    """
    queryset = queryset.order_by("pk")
    last_pk: Any = None
    while True:
        page = queryset.filter(pk__gt=last_pk) if last_pk is not None else queryset
        instances = list(page[:chunk_size])
        if not instances:
            break
        yield from instances
        last_pk = instances[-1].pk
