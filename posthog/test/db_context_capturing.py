from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS, connections
from django.test.utils import CaptureQueriesContext


@contextmanager
def capture_db_queries(connection_name=DEFAULT_DB_ALIAS):
    """
    Very simply wrapper around django's `CaptureQueriesContext` that by default
    uses the `default` database connection.
    """
    db_connection = connections[connection_name]
    with CaptureQueriesContext(db_connection) as capture_query_context:
        yield capture_query_context
