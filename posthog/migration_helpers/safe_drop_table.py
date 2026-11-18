"""Drop retired tables without making a live query the deadlock victim.

`DROP TABLE` takes ACCESS EXCLUSIVE on the dropped table and on every table its own
foreign keys reference, one relation at a time while the statement runs. When the retired
table holds keys into posthog_team, posthog_organization or posthog_user, that order crosses
the order of a live query that reads both, and the two sessions deadlock. `lock_phase.py`
has the full reasoning.

This operation takes the locks from the migration side first:

    from posthog.migration_helpers import SafeDropTable

    operations = [
        SafeDropTable(["posthog_oldfeature", "posthog_oldfeaturerun"]),
    ]

It reads the referenced parents out of pg_constraint and locks every parent, then the
dropped tables, with `lock_tables`, so the drop needs no new lock.

The operation is idempotent, so a bin/migrate retry is free. It tracks no Django state, so
the model still has to leave state a full deploy cycle earlier with
`SeparateDatabaseAndState` plus a `DropForeignKey` for each key into a hot parent.
`safe-django-migrations.md` ("Dropping Tables") has the phases and the full reasoning.
"""

from collections.abc import Sequence

from django.db import router
from django.db.migrations.operations.base import Operation

from posthog.migration_helpers.lock_phase import lock_tables, quote_tables

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
        parents = sorted(set(referenced) - set(present))

        lock_tables(schema_editor, [*parents, *present])
        schema_editor.execute(f"DROP TABLE IF EXISTS {quote_tables(schema_editor, present)}")

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        raise NotImplementedError("SafeDropTable is irreversible; recreate the table in a new migration")

    def describe(self) -> str:
        return f"Drop table {', '.join(sorted(self.tables))} under a deterministic lock order"

    @staticmethod
    def _query(schema_editor, sql: str, tables: list[str]) -> list[str]:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(sql, {"tables": tables})
            return [row[0] for row in cursor.fetchall()]
