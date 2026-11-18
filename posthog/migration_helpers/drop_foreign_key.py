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

Several keys on one table go in one op, so they share one lock phase:

    DropForeignKey("posthog_mymodel", column=["owner_id", "team_id"])

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

The drop is a catalog change and scans nothing, but a bare `DROP CONSTRAINT` locks the child
before the parent and deadlocks against live reads. This op locks every parent, then the
child, with `lock_tables`, and only then drops. `lock_phase.py` has the reasoning.

The locks last until COMMIT, so keep the op alone in its migration, next to state-only
operations at most, and give it every key on the table at once. The migration risk analyzer
blocks a migration that does otherwise.
"""

from collections.abc import Sequence

from django.db import router, transaction
from django.db.migrations.operations.base import Operation

from posthog.dataclasses import frozen
from posthog.migration_helpers.lock_phase import lock_tables

_CONSTRAINTS_SQL = """
    SELECT DISTINCT con.conname, tgt.relname
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_class tgt ON tgt.oid = con.confrelid
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
    WHERE con.contype = 'f'
      AND src.relname = %(table)s
      AND pg_table_is_visible(src.oid)
      AND (%(to_table)s IS NULL OR tgt.relname = %(to_table)s)
      AND (%(columns)s::name[] IS NULL OR att.attname = ANY(%(columns)s::name[]))
"""


@frozen
class _ForeignKeyConstraint:
    name: str
    parent: str


class DropForeignKey(Operation):
    """Drop every FOREIGN KEY on `table` that matches the given filter.

    Tracks no Django state. Use it inside `database_operations` of the same
    `SeparateDatabaseAndState` that removes the field or model from state.

    Arguments:
        table: the child table holding the constraint, e.g. `"posthog_mymodel"`. A raw
            table name rather than a model name, because the model or field is leaving
            Django's state in this same migration and may no longer resolve.
        column: the child column, e.g. `"owner_id"`, or a list of them. Note the `_id`
            suffix Django gives foreign key columns.
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

    def __init__(self, table: str, column: str | Sequence[str] | None = None, to_table: str | None = None) -> None:
        columns = [column] if isinstance(column, str) else list(column or [])
        if not columns and to_table is None:
            raise ValueError("DropForeignKey needs a column, a to_table, or both")
        self.table = table
        self.columns = columns
        self.to_table = to_table

    def state_forwards(self, app_label, state) -> None:
        pass

    def _constraints(self, schema_editor) -> list[_ForeignKeyConstraint]:
        """Every key that matches the filter, sorted by constraint name."""
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                _CONSTRAINTS_SQL,
                {"table": self.table, "to_table": self.to_table, "columns": self.columns or None},
            )
            return [_ForeignKeyConstraint(name=name, parent=parent) for name, parent in sorted(cursor.fetchall())]

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        # A product app in products/db_routing.yaml migrates on its own database. Django still
        # traverses this migration on the other aliases, and a raw catalog query cannot tell
        # them apart, so a same-named table elsewhere would lose its foreign key.
        if not router.allow_migrate(schema_editor.connection.alias, app_label):
            return
        constraints = self._constraints(schema_editor)
        if not constraints:
            return
        # A key that references its own table names the child as its parent, and the child
        # goes last in the lock list.
        parents = sorted({constraint.parent for constraint in constraints} - {self.table})
        drops = ", ".join(f"DROP CONSTRAINT {schema_editor.quote_name(constraint.name)}" for constraint in constraints)
        # LOCK TABLE needs a transaction. Inside an atomic migration this is a savepoint.
        # Under atomic = False it is a transaction of its own, which lets go of the parents
        # as soon as the drops finish.
        with transaction.atomic(using=schema_editor.connection.alias):
            lock_tables(schema_editor, [*parents, self.table])
            schema_editor.execute(f"ALTER TABLE {schema_editor.quote_name(self.table)} {drops}")

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        raise NotImplementedError("DropForeignKey is irreversible; add the constraint back with AddForeignKeyNotValid")

    def describe(self) -> str:
        target = ", ".join(self.columns) or f"-> {self.to_table}"
        return f"Drop foreign key on {self.table} ({target})"
