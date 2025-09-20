from collections.abc import Generator
from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS, connections
from django.test.utils import CaptureQueriesContext


@contextmanager
def capture_db_queries() -> Generator[CaptureQueriesContext, None, None]:
    db_connection = connections[DEFAULT_DB_ALIAS]
    with CaptureQueriesContext(db_connection) as capture_query_context:
        yield capture_query_context
