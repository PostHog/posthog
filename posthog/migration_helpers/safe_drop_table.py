"""Drop retired tables without making a live query the deadlock victim.

`DROP TABLE` takes ACCESS EXCLUSIVE on the dropped table and on every table its own
foreign keys reference, one relation at a time while the statement runs. An application
query takes AccessShare on the tables it reads, also one at a time, in whatever order its
plan picks. When the retired table holds keys into posthog_team, posthog_organization or
posthog_user, the two orders cross and the two sessions form a real deadlock cycle.

A short `lock_timeout` does not save the application query. A cycle is resolved by the
deadlock detector rather than by the lock timeout, and the backend that finds the cycle is
the one that aborts. The application query enters the wait first, so Postgres kills the
read and the user sees a 500 on a screen unrelated to the deploy.

This operation removes the cycle from the migration side:

    from posthog.migration_helpers import SafeDropTable

    operations = [
        SafeDropTable(["posthog_oldfeature", "posthog_oldfeaturerun"]),
    ]

It reads the referenced parents out of pg_constraint, takes ACCESS EXCLUSIVE on every one
of them in a single `LOCK TABLE`, and only then runs the drop, so the drop needs no new
lock. The lock phase runs under a budget derived from the server's own `deadlock_timeout`,
so the migration always abandons its wait before any peer has waited long enough to run
the detector. The migration loses the race, bin/migrate retries it, and no application
query is ever the victim.

The operation is idempotent, so a bin/migrate retry is free. It tracks no Django state, so
the model still has to leave state a full deploy cycle earlier with
`SeparateDatabaseAndState` plus a `DropForeignKey` for each key into a hot parent.
`safe-django-migrations.md` ("Dropping Tables") has the phases and the full reasoning.
"""

from collections.abc import Sequence

from django.db import router
from django.db.migrations.operations.base import Operation

_EXISTING_TABLES_SQL = """
    SELECT relname
    FROM pg_class
    WHERE relname = ANY(%(tables)s)
      AND relkind = 'r'
      AND pg_table_is_visible(oid)
"""

_REFERENCED_TABLES_SQL = """
    SELECT DISTINCT tgt.relname
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_class tgt ON tgt.oid = con.confrelid
    WHERE con.contype = 'f'
      AND src.relname = ANY(%(tables)s)
      AND pg_table_is_visible(src.oid)
"""

_PARTITIONED_TABLES_SQL = """
    SELECT c.relname
    FROM pg_class c
    WHERE c.relname = ANY(%(tables)s)
      AND c.relkind IN ('r', 'p')
      AND pg_table_is_visible(c.oid)
      AND (
        c.relkind = 'p'
        OR EXISTS (SELECT 1 FROM pg_inherits WHERE inhrelid = c.oid OR inhparent = c.oid)
      )
"""


class SafeDropTable(Operation):
    """Drop one or more retired tables under a deterministic, time-boxed lock phase.

    Arguments:
        tables: one raw table name, or a list of them. Raw names rather than model names,
            because the models left Django's state in an earlier migration and no longer
            resolve. A single name rather than a list is accepted because one table is the
            common case. Django's migration writer maps a captured argument onto the
            parameter name, so this stays a named parameter and never becomes `*tables`.

    Pass every table of one retirement in a single operation. They are locked and dropped
    together, so a key between two of them needs no ordering at the call site.

    A partitioned table, and any table in an inheritance hierarchy, is refused rather than
    dropped. The lock list covers the named tables and their foreign-key parents, and a
    hierarchy needs its own members in the list as well.
    """

    # A no-op reverse would report success and leave the table gone.
    reversible = False
    reduces_to_sql = True

    def __init__(self, tables: str | Sequence[str]) -> None:
        names = [tables] if isinstance(tables, str) else list(tables)
        if not names:
            raise ValueError("SafeDropTable needs at least one table")
        self.tables = names

    def state_forwards(self, app_label, state) -> None:
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        # Django traverses this migration on every alias, and a raw catalog query cannot
        # tell a routed product database from the main one.
        if not router.allow_migrate(schema_editor.connection.alias, app_label):
            return
        # SET LOCAL outside a transaction only warns, leaving the lock phase unbounded.
        if not schema_editor.connection.in_atomic_block:
            raise RuntimeError("SafeDropTable needs an atomic migration; remove `atomic = False`")

        # A partitioned root carries relkind 'p', so the existence query cannot see it and
        # the absent-table return below would report success for a table that is still
        # there. A partition's inheritance parent is not a foreign-key target either, so it
        # never enters the lock list and the drop takes ACCESS EXCLUSIVE on it while the
        # statement runs.
        hierarchies = sorted(self._query(schema_editor, _PARTITIONED_TABLES_SQL, self.tables))
        if hierarchies:
            raise RuntimeError(
                f"SafeDropTable cannot drop {', '.join(hierarchies)}: a partitioned or inherited table needs its"
                " whole hierarchy in the lock list, and this operation collects only the named tables and their"
                ' foreign-key parents. See safe-django-migrations.md ("Dropping Tables").'
            )

        present = sorted(self._query(schema_editor, _EXISTING_TABLES_SQL, self.tables))
        if not present:
            return
        referenced = self._query(schema_editor, _REFERENCED_TABLES_SQL, present)

        self._lock(schema_editor, sorted(set(present) | set(referenced)))
        schema_editor.execute(f"DROP TABLE IF EXISTS {self._quote(schema_editor, present)}")

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        raise NotImplementedError("SafeDropTable is irreversible; recreate the table in a new migration")

    def describe(self) -> str:
        return f"Drop table {', '.join(sorted(self.tables))} under a deterministic lock order"

    def _lock(self, schema_editor, tables: list[str]) -> None:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT (SELECT setting::int FROM pg_settings WHERE name = 'deadlock_timeout'),"
                " current_setting('lock_timeout'), current_setting('statement_timeout')"
            )
            deadlock_ms, previous_lock, previous_statement = cursor.fetchone()
        # Half, so the migration abandons its wait before any peer waiting on the
        # migration can run the detector and be killed for it.
        budget_ms = max(1, deadlock_ms // 2)
        # lock_timeout bounds one attempt and statement_timeout bounds the sequence, so
        # several contended tables cannot add up past the budget between them.
        schema_editor.execute(f"SET LOCAL lock_timeout = '{budget_ms}ms'")
        schema_editor.execute(f"SET LOCAL statement_timeout = '{budget_ms}ms'")
        schema_editor.execute(f"LOCK TABLE {self._quote(schema_editor, tables)} IN ACCESS EXCLUSIVE MODE")
        # The drop needs no new lock, so put back what the transaction came in with. Not
        # DEFAULT: an earlier operation in the same migration can hold a value of its own,
        # and ValidateConstraint disables both timeouts for exactly that reason.
        schema_editor.execute("SELECT set_config('lock_timeout', %s, true)", [previous_lock])
        schema_editor.execute("SELECT set_config('statement_timeout', %s, true)", [previous_statement])

    @staticmethod
    def _quote(schema_editor, tables: list[str]) -> str:
        return ", ".join(schema_editor.quote_name(table) for table in tables)

    @staticmethod
    def _query(schema_editor, sql: str, tables: list[str]) -> list[str]:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(sql, {"tables": tables})
            return [row[0] for row in cursor.fetchall()]
