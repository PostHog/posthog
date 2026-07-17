"""Two-phase FOREIGN KEY helper: add the FK as NOT VALID, then VALIDATE separately.

Adding a foreign key the normal way (a plain `ForeignKey` in a model, which Django
emits inline in `CREATE TABLE` or as `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY`)
takes a SHARE ROW EXCLUSIVE lock on the *referenced parent* table while the constraint
is added, and then validates every existing child row under that lock. On a hot parent
table (posthog_team, posthog_user, ...) that SHARE ROW EXCLUSIVE conflicts with the
ROW EXCLUSIVE lock every INSERT/UPDATE/DELETE on the parent holds, so under write
traffic the lock request queues, lock_timeout cancels it, and every bin/migrate retry
repeats the stall. This blocked a prod deploy.

Be honest about the lock nuance - there are two distinct options, and only one is truly
lock-free:

1. `db_constraint=False` on the `ForeignKey` (declared in the model) is the only path
   that takes NO lock on the parent at all. `CREATE TABLE` / `AddField` then emit no FK
   constraint - the relationship is enforced in application code only. Reach for this when
   the FK targets a hot table and you can live without database-level enforcement; it is
   the only option that would have saved the deploy above.
2. This helper splits the constraint into two phases so a real database FK can still be
   added with a much smaller lock window:

   - `AddForeignKeyNotValid` runs `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ...
     NOT VALID`. This still takes a *brief* SHARE ROW EXCLUSIVE lock on the parent for
     the catalog metadata add - it is NOT lock-free - but it skips the row-validation
     scan, so the lock window is metadata-only rather than scan-length.
   - `ValidateForeignKey` later runs `ALTER TABLE ... VALIDATE CONSTRAINT ...`, which
     scans the child rows under SHARE UPDATE EXCLUSIVE and takes no lock on the parent.

The intended author workflow for a hot-table FK is:

    # model: declare the FK with db_constraint=False so CREATE TABLE / AddField emit
    # no parent lock at all. on_delete stays a Django/Python concern - the collector
    # handles cascades and signals; Django never emits a DB-level ON DELETE action.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)

    # 00xx_add_fk_not_valid.py  (brief SHARE ROW EXCLUSIVE on the parent)
    operations = [
        AddForeignKeyNotValid(
            model_name="mymodel",
            name="mymodel_team_id_fk",
            column="team_id",
            to_table="posthog_team",
            to_column="id",
        ),
    ]

    # 00yy_validate_fk.py  (SHARE UPDATE EXCLUSIVE on the child, no parent lock)
    operations = [
        ValidateForeignKey(model_name="mymodel", name="mymodel_team_id_fk"),
    ]

Put the two phases in SEPARATE migrations (validate after the add has deployed), or in
the same migration with `atomic = False` - never the same atomic migration, or the ADD's
lock is held through the VALIDATE scan and the split buys nothing.

The ADD phase deliberately does NOT disable lock_timeout / statement_timeout: it's a
brief metadata-only ALTER, so it should fail fast on lock contention (the default
lock_timeout) instead of queuing the SHARE ROW EXCLUSIVE lock behind in-flight writes on
the parent and stalling it further. A bin/migrate retry re-attempts once the lock is
free. The VALIDATE phase reuses `ValidateConstraint`, which disables the timeouts so a
deploy-time statement_timeout can't kill the scan mid-flight.

Both phases are idempotent (bin/migrate re-runs the whole migration on failure): the add
skips if the constraint already exists, the validate skips if it is already validated.

`ValidateConstraint` from `not_valid_constraint` works unchanged for FK constraints -
`VALIDATE CONSTRAINT` and the `pg_constraint.convalidated` probe are constraint-type
agnostic. `ValidateForeignKey` is a thin subclass of it so the two FK phases read as a
pair at the call site and the validate op deconstructs under its own name.
"""

from django.db.migrations.operations.base import Operation

from posthog.migration_helpers.not_valid_constraint import ValidateConstraint, _constraint_validity


class ValidateForeignKey(ValidateConstraint):
    """Phase 2 for a FOREIGN KEY: VALIDATE an FK previously added with NOT VALID.

    `VALIDATE CONSTRAINT` and the `pg_constraint.convalidated` probe don't care whether
    the constraint is a CHECK or a FOREIGN KEY, so the behaviour is entirely inherited from
    `ValidateConstraint`. This exists as a real subclass (not an alias) so it deconstructs
    under its own name - a squash that touches an FK validate op round-trips as
    `ValidateForeignKey`, matching the name the docs tell authors to use, and the migration
    analyzer can tell FK validation apart from CHECK validation.
    """

    pass


class AddForeignKeyNotValid(Operation):
    """Phase 1: add a FOREIGN KEY constraint with NOT VALID (no child-row scan).

    Emits the same FK DDL Django would, minus the row scan: `ALTER TABLE ... ADD
    CONSTRAINT ... FOREIGN KEY (column) REFERENCES to_table (to_column) DEFERRABLE
    INITIALLY DEFERRED NOT VALID`. This takes a brief SHARE ROW EXCLUSIVE lock on the
    *referenced parent* table for the catalog metadata add - it is NOT lock-free, but it
    skips validating existing child rows under that lock. Follow up with
    `ValidateForeignKey` in a separate migration.

    The constraint is DEFERRABLE INITIALLY DEFERRED to match Django's Postgres FKs (so
    child-before-parent inserts inside one transaction still pass), and carries no ON
    DELETE action - exactly like a Django FK, whose cascades are handled by the Python
    collector, not the database. This keeps it a true drop-in for the model's FK.

    This op tracks no Django model state: the relationship is expected to already be in
    state from a `ForeignKey(..., db_constraint=False)` on the model (whose CreateModel /
    AddField emitted no parent lock). The migration class needs `atomic = False` if this
    op shares a migration with `ValidateForeignKey`.

    Arguments:
        model_name: the child model (used to resolve its db_table and for state checks).
        name: the constraint name. Must match what you pass to `ValidateForeignKey`.
        column: the child FK column, e.g. `"team_id"`.
        to_table: the referenced parent table, e.g. `"posthog_team"`.
        to_column: the referenced parent column. Defaults to `"id"`.
    """

    reversible = True

    def __init__(
        self,
        model_name: str,
        name: str,
        column: str,
        to_table: str,
        to_column: str = "id",
    ) -> None:
        self.model_name = model_name
        self.name = name
        self.column = column
        self.to_table = to_table
        self.to_column = to_column

    def state_forwards(self, app_label, state) -> None:
        pass  # the relationship is already tracked by the model's db_constraint=False FK

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        # No timeout disabling here: ADD CONSTRAINT ... NOT VALID is a brief metadata-only
        # ALTER (no child-row scan), so it should keep the default lock_timeout and fail
        # fast on contention rather than queue the SHARE ROW EXCLUSIVE lock behind in-flight
        # writes on the parent. A bin/migrate retry re-attempts once the lock is free.
        if _constraint_validity(schema_editor, model._meta.db_table, self.name) is not None:
            return  # already added; a bin/migrate retry is a no-op
        table = schema_editor.quote_name(model._meta.db_table)
        name = schema_editor.quote_name(self.name)
        column = schema_editor.quote_name(self.column)
        to_table = schema_editor.quote_name(self.to_table)
        to_column = schema_editor.quote_name(self.to_column)
        # DEFERRABLE INITIALLY DEFERRED on Postgres - matches what Django emits for a FK,
        # so this stays a drop-in (deferred constraint checks survive child-before-parent
        # inserts within a transaction).
        deferrable = schema_editor.connection.ops.deferrable_sql()
        schema_editor.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({column}) REFERENCES {to_table} ({to_column}){deferrable} NOT VALID"
        )

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        model = from_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        table = schema_editor.quote_name(model._meta.db_table)
        name = schema_editor.quote_name(self.name)
        schema_editor.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")

    def deconstruct(self) -> tuple[str, list[object], dict[str, str]]:
        kwargs = {
            "model_name": self.model_name,
            "name": self.name,
            "column": self.column,
            "to_table": self.to_table,
            "to_column": self.to_column,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def describe(self) -> str:
        return f"Add FOREIGN KEY constraint {self.name} on {self.model_name} (NOT VALID)"

    @property
    def migration_name_fragment(self) -> str:
        return f"add_fk_{self.name}"
