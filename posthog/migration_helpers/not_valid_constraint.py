"""Two-phase CHECK constraint helpers: add NOT VALID, then VALIDATE separately.

Adding a constraint the normal way (Django's `AddConstraint` ->
`ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)`) validates every existing row
while holding an ACCESS EXCLUSIVE lock. On a large or hot table that blocks all
traffic for the duration of the scan. Postgres lets you split this in two:

1. `ADD CONSTRAINT ... NOT VALID` records the constraint and enforces it for
   new/changed rows. Takes only a brief ACCESS EXCLUSIVE lock; no table scan.
2. `VALIDATE CONSTRAINT` scans existing rows under SHARE UPDATE EXCLUSIVE, which
   does not block reads or writes.

`AddConstraintNotValid` does phase 1 (and tracks Django state like
`AddConstraint`, so `makemigrations --check` stays correct). `ValidateConstraint`
does phase 2.

Put them in SEPARATE migrations (validate after the add has deployed), or in the
same migration with `atomic = False` - never the same atomic migration, or the
ADD's ACCESS EXCLUSIVE lock is held through the VALIDATE scan and you've gained
nothing:

    # 0005_add_amount_check.py
    operations = [
        AddConstraintNotValid(
            model_name="mymodel",
            constraint=models.CheckConstraint(condition=Q(amount__gte=0), name="mymodel_amount_gte_0"),
        ),
    ]

    # 0006_validate_amount_check.py
    operations = [
        ValidateConstraint(model_name="mymodel", name="mymodel_amount_gte_0"),
    ]

The VALIDATE phase disables lock_timeout / statement_timeout first (like the
concurrent index helpers): otherwise a deploy-time statement_timeout would kill
the scan mid-flight on a large table and every bin/migrate retry would do the
same. VALIDATE only takes SHARE UPDATE EXCLUSIVE, so waiting for the lock doesn't
block traffic. The ADD phase deliberately does NOT touch the timeouts: it's a
brief metadata-only ALTER under ACCESS EXCLUSIVE, so it should fail fast on lock
contention (the default lock_timeout) instead of queuing the lock behind in-flight
queries and stalling the table.

Both phases are idempotent (bin/migrate re-runs the whole migration on failure):
the add skips if the constraint already exists, the validate skips if it is
already validated.
"""

from django.db import migrations
from django.db.migrations.operations.base import Operation
from django.db.models import CheckConstraint

import structlog

from posthog.migration_helpers.concurrent_index import _disable_timeouts

logger = structlog.get_logger(__name__)


def _constraint_validity(schema_editor, table_name: str, constraint_name: str) -> bool | None:
    """None if the constraint doesn't exist, else its convalidated flag."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.convalidated
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            WHERE c.conname = %s AND t.relname = %s
            """,
            [constraint_name, table_name],
        )
        row = cursor.fetchone()
        return None if row is None else bool(row[0])


class AddConstraintNotValid(migrations.AddConstraint):
    """Phase 1: add a CHECK constraint with NOT VALID (no table scan).

    Same arguments as Django's `AddConstraint` (model_name + constraint), but
    emits `ADD CONSTRAINT ... NOT VALID` so existing rows aren't scanned under an
    ACCESS EXCLUSIVE lock. Follow up with `ValidateConstraint` in a separate
    migration. CHECK constraints only - NOT VALID doesn't apply to UNIQUE
    constraints (build a unique index with `SafeAddIndexConcurrently` instead).
    """

    # django-stubs doesn't expose these AddConstraint instance attributes, so
    # declare them for mypy (set by AddConstraint.__init__).
    model_name: str
    constraint: CheckConstraint

    def __init__(self, model_name, constraint) -> None:
        if not isinstance(constraint, CheckConstraint):
            raise ValueError(
                "AddConstraintNotValid only supports CheckConstraint - NOT VALID does not apply to "
                "other constraint types. For a unique constraint, build a unique index with "
                "SafeAddIndexConcurrently."
            )
        super().__init__(model_name, constraint)

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        # No timeout disabling here: NOT VALID is a brief metadata-only ALTER (no
        # table scan), so it should keep the default lock_timeout and fail fast on
        # lock contention rather than queue an ACCESS EXCLUSIVE lock behind in-flight
        # queries. A bin/migrate retry re-attempts once the lock is free.
        if _constraint_validity(schema_editor, model._meta.db_table, self.constraint.name) is not None:
            return  # already added; a bin/migrate retry is a no-op
        schema_editor.execute(f"{self.constraint.create_sql(model, schema_editor)} NOT VALID")

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        model = from_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        table = schema_editor.quote_name(model._meta.db_table)
        name = schema_editor.quote_name(self.constraint.name)
        schema_editor.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")

    def describe(self) -> str:
        return f"Add CHECK constraint {self.constraint.name} on {self.model_name} (NOT VALID)"


class ValidateConstraint(Operation):
    """Phase 2: VALIDATE a constraint previously added with NOT VALID.

    Scans existing rows under SHARE UPDATE EXCLUSIVE (doesn't block reads or
    writes). Pure database operation - the constraint is already in Django state
    from the `AddConstraintNotValid` in an earlier migration, so this changes no
    state. Idempotent: skips if the constraint is already validated.
    """

    reversible = True

    def __init__(self, model_name: str, name: str) -> None:
        self.model_name = model_name
        self.name = name

    def state_forwards(self, app_label, state) -> None:
        pass  # the constraint is already tracked by the earlier AddConstraintNotValid

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        _disable_timeouts(schema_editor)  # statement_timeout must not kill the VALIDATE scan mid-flight
        if _constraint_validity(schema_editor, model._meta.db_table, self.name):
            return  # already validated; a bin/migrate retry is a no-op
        table = schema_editor.quote_name(model._meta.db_table)
        name = schema_editor.quote_name(self.name)
        schema_editor.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        pass  # validation isn't reversible; the constraint itself is dropped by the add op's reverse

    def deconstruct(self) -> tuple[str, list[object], dict[str, str]]:
        return (self.__class__.__qualname__, [], {"model_name": self.model_name, "name": self.name})

    def describe(self) -> str:
        return f"Validate constraint {self.name} on {self.model_name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"validate_{self.name}"
