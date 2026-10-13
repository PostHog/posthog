"""Take fields out of Django's model state and leave their columns in Postgres."""

from django.db import migrations
from django.db.migrations.operations.base import Operation


def untrack_field(
    model_name: str,
    *field_names: str,
    database_operations: list[Operation] | None = None,
) -> migrations.SeparateDatabaseAndState:
    """Stop Django tracking one or more fields, without dropping their columns.

    This is phase 1 of a column retirement for a field you want off the model class now.
    Django names every concrete field in every SELECT and INSERT it writes, so the field has
    to leave model state in a deploy where the column still exists. Otherwise the release
    that drops the column is also the first release whose code stops asking for it, and
    every pod still on the old release fails every query against the table.

    Delete the field from the model, run makemigrations, then replace the generated
    RemoveField operations with this helper.

    Use deprecate_field() instead when you would rather keep the field on the model and
    write no migration at all.

    The field must already be null=True, for the same reason deprecate_field() refuses a
    field that is not. Django stops naming the column in INSERTs once the field leaves state,
    so a NOT NULL column with no database default rejects every insert the next release
    writes. This helper takes field names rather than fields, so it cannot check that for you.

    Args:
        model_name: The model the fields belong to, lowercase, as migrations spell it.
        field_names: One or more fields to take out of model state.
        database_operations: Operations to run alongside the state change. Pass
            DropForeignKey(...) when an untracked column carries a foreign key. That drop is
            required: Django stops cascading into a relation it cannot see, and the deferred
            constraint then fails the parent delete at COMMIT, permanently.
    """
    if not field_names:
        raise ValueError("untrack_field needs at least one field name")

    return migrations.SeparateDatabaseAndState(
        state_operations=[migrations.RemoveField(model_name=model_name, name=name) for name in field_names],
        database_operations=database_operations,
    )
