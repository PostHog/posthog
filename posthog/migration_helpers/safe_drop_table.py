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
        SafeDropTable("posthog_oldfeature", "posthog_oldfeaturerun"),
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


class SafeDropTable(Operation):
    """Drop one or more retired tables under a deterministic, time-boxed lock phase.

    Arguments:
        *tables: raw table names, for example `"posthog_oldfeature"`. Raw names rather
            than model names, because the models left Django's state in an earlier
            migration and no longer resolve.

    Pass every table of one retirement in a single operation. They are locked and dropped
    together, so a key between two of them needs no ordering at the call site.
    """

    # A no-op reverse would report success and leave the table gone.
    reversible = False
    reduces_to_sql = True

    def __init__(self, *tables: str) -> None:
        if not tables:
            raise ValueError("SafeDropTable needs at least one table")
        self.tables = list(tables)

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
            cursor.execute("SELECT setting::int FROM pg_settings WHERE name = 'deadlock_timeout'")
            deadlock_ms = cursor.fetchone()[0]
        # Half, so the migration abandons its wait before any peer waiting on the
        # migration can run the detector and be killed for it.
        budget_ms = max(1, deadlock_ms // 2)
        # lock_timeout bounds one attempt and statement_timeout bounds the sequence, so
        # several contended tables cannot add up past the budget between them.
        schema_editor.execute(f"SET LOCAL lock_timeout = '{budget_ms}ms'")
        schema_editor.execute(f"SET LOCAL statement_timeout = '{budget_ms}ms'")
        schema_editor.execute(f"LOCK TABLE {self._quote(schema_editor, tables)} IN ACCESS EXCLUSIVE MODE")
        # The drop needs no new lock, so hand the rest of the migration back to the
        # session values bin/migrate connected with.
        schema_editor.execute("SET LOCAL lock_timeout = DEFAULT")
        schema_editor.execute("SET LOCAL statement_timeout = DEFAULT")

    @staticmethod
    def _quote(schema_editor, tables: list[str]) -> str:
        return ", ".join(schema_editor.quote_name(table) for table in tables)

    @staticmethod
    def _query(schema_editor, sql: str, tables: list[str]) -> list[str]:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(sql, {"tables": tables})
            return [row[0] for row in cursor.fetchall()]
