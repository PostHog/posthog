"""Functional tests for AddFieldIfMissing's column probe.

Each test creates and drops a real table inside the standard test database, so
the probe runs against live Postgres catalogs.
"""

import uuid

import pytest

from django.db import connection, models
from django.db.migrations.state import ModelState, ProjectState
from django.test.utils import CaptureQueriesContext

from posthog.migration_helpers.squash_idempotent import AddFieldIfMissing

MODEL_NAME = "TmpSquashModel"
FIELD_NAME = "amount"


@pytest.fixture
def temp_table():
    table = f"test_sqidem_{uuid.uuid4().hex[:8]}"
    try:
        yield table
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}"')


def _state(table: str, *, with_field: bool) -> ProjectState:
    fields: list = [("id", models.AutoField(primary_key=True))]
    if with_field:
        fields.append((FIELD_NAME, models.IntegerField(null=True)))
    state = ProjectState()
    state.add_model(ModelState(app_label="posthog", name=MODEL_NAME, fields=fields, options={"db_table": table}))
    return state


def _create_table(table: str, *, with_column: bool) -> None:
    column = ", amount int" if with_column else ""
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE "{table}" (id serial primary key{column})')


def _apply_forwards(table: str) -> None:
    op = AddFieldIfMissing(model_name=MODEL_NAME, name=FIELD_NAME, field=models.IntegerField(null=True))
    with connection.schema_editor(atomic=False) as schema_editor:
        op.database_forwards(
            "posthog",
            schema_editor,
            from_state=_state(table, with_field=False),
            to_state=_state(table, with_field=True),
        )


def _column_names(table: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum > 0", [table])
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
def test_add_field_if_missing_adds_absent_column(temp_table):
    _create_table(temp_table, with_column=False)

    _apply_forwards(temp_table)

    assert FIELD_NAME in _column_names(temp_table)


@pytest.mark.django_db
def test_add_field_if_missing_skips_present_column_after_one_probe_statement(temp_table):
    _create_table(temp_table, with_column=True)

    with CaptureQueriesContext(connection) as queries:
        _apply_forwards(temp_table)  # a second ADD COLUMN would raise DuplicateColumn

    assert FIELD_NAME in _column_names(temp_table)
    # Two statements can disagree when another migrate process commits an
    # ADD COLUMN between them, which is how the probe used to abort a migrate
    # run. One statement leaves no window for that.
    assert len(queries) == 1, f"the probe must be one statement, got {[q['sql'] for q in queries]}"
