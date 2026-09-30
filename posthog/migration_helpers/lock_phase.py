"""Take every lock a drop needs before the drop runs.

`DROP TABLE` and `ALTER TABLE ... DROP CONSTRAINT` on a foreign key take ACCESS EXCLUSIVE
on the child and then on each referenced parent, one relation at a time while the statement
runs, and the transaction holds every lock until COMMIT. An application query that joins a
parent to the child takes AccessShare on the parent first. The two orders cross, and the two
sessions form a deadlock cycle.

A short `lock_timeout` alone does not stop that. The deadlock detector resolves a cycle,
not the lock timeout, and the backend that runs the detector is the one that aborts. The
application query enters the wait first, so Postgres usually kills the read.

`lock_tables` takes ACCESS EXCLUSIVE on every table in one `LOCK TABLE`, in the order the
caller gives, so the drop after it needs no new lock. Callers pass the parents first,
because that is the order a query that joins parent to child takes its locks. The wait runs
under a budget below the server's `deadlock_timeout`, so the migration abandons its own wait
before its own detector runs, and bin/migrate retries it. That biases a lock cycle toward the
migration. It does not settle every cycle: each backend arms its detector when its own wait
starts, so a query that began to wait more than the budget earlier reaches its detector first.
"""

from collections.abc import Sequence

# deadlock_timeout is a server setting this repository does not own. Half of a raised value
# is a wait long enough to queue the site behind it, so the budget has a ceiling of its own.
MAX_LOCK_BUDGET_MS = 1000


def quote_tables(schema_editor, tables: Sequence[str]) -> str:
    return ", ".join(schema_editor.quote_name(table) for table in tables)


def lock_tables(schema_editor, tables: Sequence[str]) -> None:
    """Take ACCESS EXCLUSIVE on `tables`, in order, under the deadlock budget.

    Needs an open transaction. Outside one, `SET LOCAL` only warns, and `LOCK TABLE` raises.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT (SELECT setting::int FROM pg_settings WHERE name = 'deadlock_timeout'),"
            " current_setting('lock_timeout'), current_setting('statement_timeout')"
        )
        deadlock_ms, previous_lock, previous_statement = cursor.fetchone()
    budget_ms = max(1, min(MAX_LOCK_BUDGET_MS, deadlock_ms // 2))
    # lock_timeout bounds the wait for one table and statement_timeout bounds the whole LOCK,
    # so several contended tables cannot add up past the budget between them.
    schema_editor.execute(f"SET LOCAL lock_timeout = '{budget_ms}ms'")
    schema_editor.execute(f"SET LOCAL statement_timeout = '{budget_ms}ms'")
    schema_editor.execute(f"LOCK TABLE {quote_tables(schema_editor, tables)} IN ACCESS EXCLUSIVE MODE")
    # The drop needs no new lock, so put back what the transaction came in with. Not
    # DEFAULT: an earlier operation in the same migration can hold a value of its own,
    # and ValidateConstraint disables both timeouts for exactly that reason.
    schema_editor.execute(
        "SELECT set_config('lock_timeout', %s, true), set_config('statement_timeout', %s, true)",
        [previous_lock, previous_statement],
    )
