from contextlib import contextmanager
import threading
from typing import List
from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.execute import sync_execute


@contextmanager
def failhard_threadhook_context():
    """
    Context manager to ensure that exceptions raised by threads are treated as a
    test failure.
    """

    def raise_hook(args: threading.ExceptHookArgs):
        if args.exc_value is not None:
            raise args.exc_type(args.exc_value)

    old_hook, threading.excepthook = threading.excepthook, raise_hook
    try:
        yield old_hook
    finally:
        assert threading.excepthook is raise_hook
        threading.excepthook = old_hook


def run_clickhouse_statement_in_parallel(statements: List[str]):
    jobs = []
    with failhard_threadhook_context():
        for item in statements:
            thread = threading.Thread(target=sync_execute, args=(item,))
            jobs.append(thread)

        # Start the threads (i.e. calculate the random number lists)
        for j in jobs:
            j.start()

        # Ensure all of the threads have finished
        for j in jobs:
            j.join()


# Accepts any number or string arguments
def run_sql_with_exceptions(*sqls: str):
    """
    migrations.RunSQL does not raise exceptions, so we need to wrap it in a function that does.
    """

    def run_sql(database):
        run_clickhouse_statement_in_parallel(list(sqls))

    return migrations.RunPython(run_sql)
