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

The op deliberately does not touch lock_timeout, exactly like `AddForeignKeyNotValid`.
Dropping a foreign key takes ACCESS EXCLUSIVE on the referenced parent for a metadata-only
change held for microseconds, so it should fail fast on contention under whatever
lock_timeout the connection carries, rather than queue that lock and stall the parent.
Never disable the timeout here: on a hot parent an unbounded wait blocks every query that
arrives behind it. A bin/migrate retry re-attempts once the lock is free.
"""

from django.db import router
from django.db.migrations.operations.base import Operation

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
        for name in self._constraint_names(schema_editor):
            schema_editor.execute(
                f"ALTER TABLE {schema_editor.quote_name(self.table)} DROP CONSTRAINT {schema_editor.quote_name(name)}"
            )

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        raise NotImplementedError("DropForeignKey is irreversible; add the constraint back with AddForeignKeyNotValid")

    def describe(self) -> str:
        target = self.column or f"-> {self.to_table}"
        return f"Drop foreign key on {self.table} ({target})"

    def _constraint_names(self, schema_editor) -> list[str]:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                _CONSTRAINT_NAMES_SQL,
                {"table": self.table, "to_table": self.to_table, "column": self.column},
            )
            return sorted({row[0] for row in cursor.fetchall()})
