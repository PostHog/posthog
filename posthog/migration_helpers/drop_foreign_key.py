"""Drop the FOREIGN KEY constraints a retired column or table still holds.

Retiring a model or a field with `SeparateDatabaseAndState` leaves the table or column in
Postgres, which is the point: old releases keep working. What it also leaves is every
foreign key that column carries, and Django can no longer see it. A parent delete stops
cascading into a relation it does not know about, so the child rows outlive the parent.
Django's foreign keys are DEFERRABLE INITIALLY DEFERRED, so Postgres does not complain
during the cascade; it checks at COMMIT, after the whole delete has run, and raises. The
delete can never succeed. Retiring a model whose table pointed at posthog_team this way
made team and organization deletion impossible until the table was dropped.

So the constraint has to go in the same migration that takes the column or table out of
Django's state:

    from posthog.migration_helpers import DropForeignKey, untrack_field

    operations = [
        untrack_field(
            "mymodel",
            "owner",
            database_operations=[DropForeignKey("posthog_mymodel", column="owner_id")],
        ),
    ]

For a whole table leaving state, name the parent instead of the column:

    migrations.SeparateDatabaseAndState(
        state_operations=[migrations.DeleteModel(name="OldFeature")],
        database_operations=[DropForeignKey("posthog_oldfeature", to_table="posthog_team")],
    )

Do not hand-write `ALTER TABLE ... DROP CONSTRAINT IF EXISTS <name>`. Django names foreign
keys with a hash suffix, so the name is not something you can derive at the call site, and
`IF EXISTS` turns a wrong guess into a migration that succeeds and drops nothing. This op
reads the names out of pg_constraint instead, which is also what makes it idempotent under
a bin/migrate retry.

The op is irreversible. Add the constraint back with `AddForeignKeyNotValid` in a new
migration rather than by unapplying this one.

Each drop runs under a short lock_timeout the op sets itself. The statement is a
metadata-only change held for microseconds, but it takes ACCESS EXCLUSIVE on the referenced
parent, and the wait for that lock is the hazard: it queues behind any in-flight read of
the parent, and every query that arrives after it queues behind the wait. On a hot parent
such as posthog_team or posthog_user that stalls the site for as long as the wait lasts.

The budget is half the server's own deadlock_timeout, and never more than a second. Two
waits are in play. A single ALTER holds its ACCESS EXCLUSIVE to COMMIT, so a child with keys
into two hot parents holds one parent while it requests the next, and that lock order
crosses the order of any live query reading both. A cycle is resolved by the deadlock
detector rather than by lock_timeout, and the backend that runs the detector is the one that
aborts. A budget under deadlock_timeout biases the cycle toward the migration, because the
op abandons its own wait before its own detector runs. It does not settle the cycle. Each
backend arms its detector when its own wait starts. An application query that began its wait
more than the budget earlier reaches its detector first, and that backend aborts itself.
bin/migrate retries the migration either way. Never widen or disable the timeout here.

The one second is a ceiling on that half, not the budget itself, because deadlock_timeout is
a server setting this repository does not own. An operator can raise it on a loaded server,
and half of a raised value is a wait long enough to queue the site behind it. A ceiling only
lowers the budget, so the bias above holds whatever the server reports.
"""

from django.db import router
from django.db.migrations.operations.base import Operation

_MAX_LOCK_BUDGET_MS = 1000

_CONSTRAINT_NAMES_SQL = """
    SELECT con.conname
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_class tgt ON tgt.oid = con.confrelid
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
    WHERE con.contype = 'f'
      AND src.relname = %(table)s
      AND pg_table_is_visible(src.oid)
      AND (%(to_table)s IS NULL OR tgt.relname = %(to_table)s)
      AND (%(column)s IS NULL OR att.attname = %(column)s)
"""


class DropForeignKey(Operation):
    """Drop every FOREIGN KEY on `table` that matches the given filter.

    Tracks no Django state. Use it inside `database_operations` of the same
    `SeparateDatabaseAndState` that removes the field or model from state.

    Arguments:
        table: the child table holding the constraint, e.g. `"posthog_mymodel"`. A raw
            table name rather than a model name, because the model or field is leaving
            Django's state in this same migration and may no longer resolve.
        column: the child column, e.g. `"owner_id"`. Note the `_id` suffix Django gives
            foreign key columns.
        to_table: the referenced parent table, e.g. `"posthog_team"`.

    Pass `column`, `to_table`, or both. Passing neither would drop every foreign key on the
    table, which is never what a retirement means, so it raises instead.
    """

    # A dropped constraint cannot be put back: its definition is recorded nowhere this op can
    # read, and the arguments do not carry the column list or the referenced column. A no-op
    # reverse would report success while Django restored the field to model state with no
    # constraint behind it, which is the state-versus-schema drift this helper exists to stop.
    # Use AddForeignKeyNotValid to add the constraint back in a new migration instead.
    reversible = False
    reduces_to_sql = True

    def __init__(self, table: str, column: str | None = None, to_table: str | None = None) -> None:
        if column is None and to_table is None:
            raise ValueError("DropForeignKey needs a column, a to_table, or both")
        self.table = table
        self.column = column
        self.to_table = to_table

    def state_forwards(self, app_label, state) -> None:
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        # A product app in products/db_routing.yaml migrates on its own database. Django still
        # traverses this migration on the other aliases, and a raw catalog query cannot tell
        # them apart, so a same-named table elsewhere would lose its foreign key.
        if not router.allow_migrate(schema_editor.connection.alias, app_label):
            return
        names = self._constraint_names(schema_editor)
        if not names:
            return
        # A transaction-local setting ends with the migration's transaction, but a migration
        # marked atomic = False has no transaction to hold it, so there the setting is a
        # session one this op puts back itself.
        transaction_local = schema_editor.connection.in_atomic_block
        previous = self._lock_timeout(schema_editor)
        self._set_lock_timeout(schema_editor, f"{self._lock_budget_ms(schema_editor)}ms", transaction_local)
        for name in names:
            schema_editor.execute(
                f"ALTER TABLE {schema_editor.quote_name(self.table)} DROP CONSTRAINT {schema_editor.quote_name(name)}"
            )
        # A drop that times out must not restore: the rollback carries the setting back, and
        # the aborted transaction would reject the restore and mask the lock timeout.
        self._set_lock_timeout(schema_editor, previous, transaction_local)

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        raise NotImplementedError("DropForeignKey is irreversible; add the constraint back with AddForeignKeyNotValid")

    def describe(self) -> str:
        target = self.column or f"-> {self.to_table}"
        return f"Drop foreign key on {self.table} ({target})"

    def _lock_budget_ms(self, schema_editor) -> int:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SELECT setting::int FROM pg_settings WHERE name = 'deadlock_timeout'")
            return max(1, min(_MAX_LOCK_BUDGET_MS, cursor.fetchone()[0] // 2))

    def _lock_timeout(self, schema_editor) -> str:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('lock_timeout')")
            return cursor.fetchone()[0]

    def _set_lock_timeout(self, schema_editor, value: str, transaction_local: bool) -> None:
        # set_config takes the value as a parameter, which SET does not.
        schema_editor.execute("SELECT set_config('lock_timeout', %s, %s)", [value, transaction_local])

    def _constraint_names(self, schema_editor) -> list[str]:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                _CONSTRAINT_NAMES_SQL,
                {"table": self.table, "to_table": self.to_table, "column": self.column},
            )
            return sorted({row[0] for row in cursor.fetchall()})
