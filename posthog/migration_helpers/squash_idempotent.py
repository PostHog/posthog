"""Idempotent Add* operations for nextgensquash's finalize_fks files.

A finalize_fks migration adds the FK fields, indexes, and constraints the
squash's initial deferred to break dependency cycles. On a fresh database it
must behave exactly like the plain Django operations. On an existing database
the schema it adds is already there — the historical chain built it — and the
file runs once as a real migration (it carries no `replaces`, so Django plans
it). Each operation here probes the catalog and skips instead of failing.
State handling is inherited unchanged.

Backwards is a deliberate no-op on every operation: when the forward pass
skipped (the historical chain had already built the object), the inherited
reverse would drop a column, index, or constraint the squash never created —
destroying data on any database that migrates back below the finalize file.
Migration tests walk backwards through these files, so they must be safely
reversible; re-applying forward is idempotent either way.
"""

from django.db import migrations
from django.db.models.constraints import BaseConstraint


def _table_constraints(schema_editor, table: str) -> dict:
    with schema_editor.connection.cursor() as cursor:
        return schema_editor.connection.introspection.get_constraints(cursor, table)


def _existing_constraint_names(schema_editor, table: str) -> set[str]:
    return set(_table_constraints(schema_editor, table))


class AddFieldIfMissing(migrations.AddField):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            # Django's own operation would no-op (unmanaged, swapped, or
            # router-excluded model); probing its absent table would crash first.
            return
        field = model._meta.get_field(self.name)
        conn = schema_editor.connection
        with conn.cursor() as cursor:
            if field.many_to_many:
                through_table = field.remote_field.through._meta.db_table
                if through_table in conn.introspection.table_names(cursor):
                    return
            else:
                columns = {c.name for c in conn.introspection.get_table_description(cursor, model._meta.db_table)}
                if field.column in columns:
                    return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        pass  # see module docstring: reversing must not drop pre-existing schema


class AddIndexIfMissing(migrations.AddIndex):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        if self.index.name in _existing_constraint_names(schema_editor, model._meta.db_table):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        pass  # see module docstring: reversing must not drop pre-existing schema


class AddConstraintIfMissing(migrations.AddConstraint):
    # django-stubs omits these runtime attributes on AddConstraint.
    model_name: str
    constraint: BaseConstraint

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        if self.constraint.name in _existing_constraint_names(schema_editor, model._meta.db_table):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        pass  # see module docstring: reversing must not drop pre-existing schema


class AlterUniqueTogetherIfMissing(migrations.AlterUniqueTogether):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        wanted: set[frozenset[str]] = set()
        for tup in self.option_value or ():
            wanted.add(frozenset(model._meta.get_field(f).column for f in tup))
        constraints = _table_constraints(schema_editor, model._meta.db_table)
        existing = {frozenset(c["columns"]) for c in constraints.values() if c.get("unique")}
        if wanted <= existing:
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        pass  # see module docstring: reversing must not drop pre-existing schema
