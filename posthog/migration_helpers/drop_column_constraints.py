"""Drop the rules a retiring column still enforces, found in the catalog rather than by name.

A column that leaves Django's state keeps every check and unique rule the database holds on
it. Once the code stops filling the column, a check that requires it rejects every insert,
and a unique rule over it guards nothing. So those rules go before the release that stops
writing the column, inside the `SeparateDatabaseAndState` that removes them from state:

    from posthog.migration_helpers import DropColumnConstraints

    migrations.SeparateDatabaseAndState(
        state_operations=[
            migrations.AlterUniqueTogether(name="mymodel", unique_together=set()),
            migrations.RemoveConstraint(model_name="mymodel", name="one_owner_set"),
        ],
        database_operations=[
            DropColumnConstraints("posthog_mymodel", columns=["owner_id", "legacy_id"]),
        ],
    )

Do not hand-write `DROP CONSTRAINT IF EXISTS <name>` or `DROP INDEX IF EXISTS <name>` for
this. Django names a `unique_together` constraint with a hash suffix, and a typed name that
does not match turns `IF EXISTS` into a migration that succeeds and drops nothing. A
database can also hold rules no migration file names any more, because an earlier swap left
them behind. This op finds every rule by the columns it covers, so it drops those too.

It drops, when any of their columns is one of `columns`:

- check, unique and exclusion constraints,
- unique indexes that no constraint owns. Postgres stores a Django `UniqueConstraint` with a
  `condition` as a plain unique index, and a swap that drops a constraint but not its index
  leaves one too.

It keeps foreign keys, which `DropForeignKey` handles, the primary key, and plain indexes,
which a later `DROP COLUMN` takes with the column.

Every drop touches only the one table, so the op locks it with `lock_tables` and drops
everything under that one lock. The drops are catalog changes and scan nothing. The op is
idempotent under a bin/migrate retry, and irreversible.
"""

from collections.abc import Sequence

from django.db import router, transaction
from django.db.migrations.operations.base import Operation

from posthog.dataclasses import frozen
from posthog.migration_helpers.lock_phase import lock_tables

# `unnest` rather than the `&&` array operator: an extension such as intarray makes
# `smallint[] && smallint[]` ambiguous, and the query then fails on that database only.
_RULES_SQL = """
    WITH target AS (
        SELECT oid FROM pg_class WHERE relname = %(table)s AND pg_table_is_visible(oid)
    ), retiring AS (
        SELECT att.attnum FROM pg_attribute att, target
        WHERE att.attrelid = target.oid AND att.attname = ANY(%(columns)s::name[])
    )
    SELECT con.conname, 'constraint'
    FROM pg_constraint con, target
    WHERE con.conrelid = target.oid
      AND con.contype IN ('c', 'u', 'x')
      AND EXISTS (SELECT 1 FROM unnest(con.conkey) AS key(attnum) WHERE key.attnum IN (SELECT attnum FROM retiring))
    UNION
    SELECT idx.relname, 'index'
    FROM pg_index ix
    JOIN target ON ix.indrelid = target.oid
    JOIN pg_class idx ON idx.oid = ix.indexrelid
    -- An index depends on each column in its keys, its expressions and its predicate.
    JOIN pg_depend dep ON dep.classid = 'pg_class'::regclass AND dep.objid = ix.indexrelid
                      AND dep.refclassid = 'pg_class'::regclass AND dep.refobjid = ix.indrelid
    WHERE ix.indisunique
      AND NOT ix.indisprimary
      AND NOT EXISTS (SELECT 1 FROM pg_constraint owner WHERE owner.conindid = ix.indexrelid)
      AND dep.refobjsubid IN (SELECT attnum FROM retiring)
"""


@frozen
class _Rule:
    name: str
    is_index: bool


class DropColumnConstraints(Operation):
    """Drop every check and unique rule on `table` that covers one of `columns`.

    Tracks no Django state. Use it inside `database_operations` of the same
    `SeparateDatabaseAndState` that removes the constraints from state.

    Arguments:
        table: the table, e.g. `"posthog_mymodel"`. A raw table name, like `DropForeignKey`.
        columns: the retiring columns, e.g. `["owner_id"]`. Note the `_id` suffix Django
            gives foreign key columns.
    """

    # The dropped definitions are recorded nowhere this op can read, so a reverse could only
    # be a no-op, and that would put the rules back into model state without the database.
    reversible = False
    reduces_to_sql = True

    def __init__(self, table: str, columns: Sequence[str]) -> None:
        if isinstance(columns, str) or not columns:
            raise ValueError("DropColumnConstraints needs a list of columns")
        self.table = table
        self.columns = list(columns)

    def state_forwards(self, app_label, state) -> None:
        pass

    def _rules(self, schema_editor) -> list[_Rule]:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(_RULES_SQL, {"table": self.table, "columns": self.columns})
            return [_Rule(name=name, is_index=kind == "index") for name, kind in sorted(cursor.fetchall())]

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        # A product app in products/db_routing.yaml migrates on its own database. A raw
        # catalog query cannot tell the aliases apart, so check the router first.
        if not router.allow_migrate(schema_editor.connection.alias, app_label):
            return
        rules = self._rules(schema_editor)
        if not rules:
            return
        constraints = [rule.name for rule in rules if not rule.is_index]
        indexes = [rule.name for rule in rules if rule.is_index]
        with transaction.atomic(using=schema_editor.connection.alias):
            lock_tables(schema_editor, [self.table])
            if constraints:
                drops = ", ".join(f"DROP CONSTRAINT {schema_editor.quote_name(name)}" for name in constraints)
                schema_editor.execute(f"ALTER TABLE {schema_editor.quote_name(self.table)} {drops}")
            if indexes:
                schema_editor.execute(f"DROP INDEX {', '.join(schema_editor.quote_name(name) for name in indexes)}")

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        raise NotImplementedError("DropColumnConstraints is irreversible; add the rules back in a new migration")

    def describe(self) -> str:
        return f"Drop check and unique rules on {self.table} ({', '.join(self.columns)})"
