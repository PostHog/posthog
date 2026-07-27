import uuid

import pytest

from django.db import connection, models, transaction
from django.db.migrations.state import ModelState, ProjectState
from django.db.utils import IntegrityError

from posthog.migration_helpers import AddForeignKeyNotValid, ValidateForeignKey

MODEL_NAME = "TmpFkModel"


@pytest.fixture
def temp_tables():
    # A one-off child + parent table plus a ProjectState model pointing at the child.
    suffix = uuid.uuid4().hex[:8]
    parent = f"test_fk_parent_{suffix}"
    child = f"test_fk_child_{suffix}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE "{parent}" (id serial primary key)')
        cursor.execute(f'CREATE TABLE "{child}" (id serial primary key, parent_id int)')
    state = ProjectState()
    state.add_model(
        ModelState(
            app_label="posthog",
            name=MODEL_NAME,
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("parent_id", models.IntegerField(null=True)),
            ],
            options={"db_table": child},
        )
    )
    try:
        yield child, parent, state
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{child}"')
            cursor.execute(f'DROP TABLE IF EXISTS "{parent}"')


def _add_op(name, parent):
    return AddForeignKeyNotValid(
        model_name=MODEL_NAME,
        name=name,
        column="parent_id",
        to_table=parent,
        to_column="id",
    )


def _apply_forwards(op, state):
    schema_editor = connection.schema_editor(atomic=False)
    schema_editor.__enter__()
    try:
        op.database_forwards("posthog", schema_editor, from_state=state, to_state=state)
    finally:
        schema_editor.__exit__(None, None, None)


def _apply_backwards(op, state):
    schema_editor = connection.schema_editor(atomic=False)
    schema_editor.__enter__()
    try:
        op.database_backwards("posthog", schema_editor, from_state=state, to_state=state)
    finally:
        schema_editor.__exit__(None, None, None)


def _convalidated(constraint_name):
    # None if the constraint is absent, else its convalidated flag.
    with connection.cursor() as cursor:
        cursor.execute("SELECT convalidated FROM pg_constraint WHERE conname = %s", [constraint_name])
        row = cursor.fetchone()
        return None if row is None else bool(row[0])


def _insert_parent(parent):
    with connection.cursor() as cursor:
        cursor.execute(f'INSERT INTO "{parent}" DEFAULT VALUES RETURNING id')
        return cursor.fetchone()[0]


def _insert_child(child, parent_id):
    with connection.cursor() as cursor:
        cursor.execute(f'INSERT INTO "{child}" (parent_id) VALUES (%s)', [parent_id])


@pytest.mark.django_db(transaction=True)
def test_add_foreign_key_not_valid_creates_unvalidated_constraint(temp_tables):
    child, parent, state = temp_tables
    name = f"{child}_parent_fk"

    _apply_forwards(_add_op(name, parent), state)

    assert _convalidated(name) is False  # present but not validated


@pytest.mark.django_db(transaction=True)
def test_add_foreign_key_not_valid_skips_existing_rows_but_enforces_new_rows(temp_tables):
    # The point of NOT VALID: a pre-existing orphan child row is tolerated, new ones aren't.
    child, parent, state = temp_tables
    name = f"{child}_parent_fk"
    _insert_child(child, 999)  # pre-existing orphan (no matching parent)

    _apply_forwards(_add_op(name, parent), state)  # succeeds despite the orphan (no scan)

    with pytest.raises(IntegrityError):
        _insert_child(child, 888)  # new orphan is rejected


@pytest.mark.django_db(transaction=True)
def test_add_foreign_key_not_valid_is_deferrable(temp_tables):
    # DEFERRABLE INITIALLY DEFERRED: a child can be inserted before its parent within one
    # transaction, with the FK checked at commit - matching Django's FK semantics. Without
    # deferrability the child insert would raise immediately.
    child, parent, state = temp_tables
    name = f"{child}_parent_fk"
    _apply_forwards(_add_op(name, parent), state)

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f'INSERT INTO "{child}" (parent_id) VALUES (4242)')  # parent 4242 not inserted yet
        cursor.execute(f'INSERT INTO "{parent}" (id) VALUES (4242)')  # added before commit

    assert _convalidated(name) is False  # commit succeeded; the deferred check passed


@pytest.mark.django_db(transaction=True)
def test_add_foreign_key_not_valid_is_idempotent(temp_tables):
    child, parent, state = temp_tables
    name = f"{child}_parent_fk"
    op = _add_op(name, parent)

    _apply_forwards(op, state)
    _apply_forwards(op, state)

    assert _convalidated(name) is False


@pytest.mark.django_db(transaction=True)
def test_add_foreign_key_not_valid_reverse_drops(temp_tables):
    child, parent, state = temp_tables
    name = f"{child}_parent_fk"
    op = _add_op(name, parent)

    _apply_forwards(op, state)
    assert _convalidated(name) is False

    _apply_backwards(op, state)
    assert _convalidated(name) is None

    _apply_backwards(op, state)  # idempotent: DROP CONSTRAINT IF EXISTS
    assert _convalidated(name) is None


@pytest.mark.django_db(transaction=True)
def test_validate_foreign_key_marks_constraint_valid(temp_tables):
    child, parent, state = temp_tables
    name = f"{child}_parent_fk"
    pid = _insert_parent(parent)
    _insert_child(child, pid)  # clean data
    _apply_forwards(_add_op(name, parent), state)
    assert _convalidated(name) is False

    _apply_forwards(ValidateForeignKey(model_name=MODEL_NAME, name=name), state)

    assert _convalidated(name) is True


@pytest.mark.django_db(transaction=True)
def test_validate_foreign_key_is_idempotent(temp_tables):
    child, parent, state = temp_tables
    name = f"{child}_parent_fk"
    _apply_forwards(_add_op(name, parent), state)
    validate = ValidateForeignKey(model_name=MODEL_NAME, name=name)

    _apply_forwards(validate, state)
    _apply_forwards(validate, state)  # already validated -> skipped

    assert _convalidated(name) is True


@pytest.mark.django_db(transaction=True)
def test_validate_foreign_key_fails_on_existing_violation(temp_tables):
    child, parent, state = temp_tables
    name = f"{child}_parent_fk"
    _insert_child(child, 999)  # existing orphan
    _apply_forwards(_add_op(name, parent), state)

    with pytest.raises(IntegrityError):
        _apply_forwards(ValidateForeignKey(model_name=MODEL_NAME, name=name), state)

    assert _convalidated(name) is False  # stays unvalidated, can retry after cleanup


def _collected_forward_sql(op, child):
    # collect_sql records statements instead of running them; the constraint is
    # absent, so the validity probe returns None and the op proceeds to emit DDL.
    state = ProjectState()
    state.add_model(
        ModelState(
            app_label="posthog",
            name=MODEL_NAME,
            fields=[("id", models.AutoField(primary_key=True)), ("parent_id", models.IntegerField(null=True))],
            options={"db_table": child},
        )
    )
    schema_editor = connection.schema_editor(atomic=False, collect_sql=True)
    schema_editor.__enter__()
    try:
        op.database_forwards("posthog", schema_editor, from_state=state, to_state=state)
    finally:
        schema_editor.__exit__(None, None, None)
    return "\n".join(schema_editor.collected_sql)


@pytest.mark.django_db
def test_add_foreign_key_not_valid_keeps_lock_timeout():
    # ADD CONSTRAINT ... NOT VALID takes a brief SHARE ROW EXCLUSIVE lock on the parent, so it
    # must keep the default lock_timeout and fail fast on contention rather than queue the lock
    # behind in-flight writes on the parent.
    op = AddForeignKeyNotValid(model_name=MODEL_NAME, name="tfk", column="parent_id", to_table="some_parent")
    collected = _collected_forward_sql(op, "test_fk_child_collect")

    assert "SET lock_timeout = 0" not in collected
    assert "SET statement_timeout = 0" not in collected
    assert "ADD CONSTRAINT" in collected.upper()
    assert "NOT VALID" in collected.upper()
    assert "DEFERRABLE INITIALLY DEFERRED" in collected.upper()  # matches Django's FK DDL
    assert "ON DELETE" not in collected.upper()  # Django handles cascade in Python, not the DB


def test_deconstruct_round_trips():
    op = AddForeignKeyNotValid(model_name=MODEL_NAME, name="tfk", column="parent_id", to_table="some_parent")
    name, args, kwargs = op.deconstruct()

    assert name == "AddForeignKeyNotValid"
    assert args == []
    rebuilt = AddForeignKeyNotValid(**kwargs)
    assert rebuilt.deconstruct() == op.deconstruct()


def test_validate_foreign_key_deconstructs_under_own_name():
    # A subclass, not an alias - so a squash round-trips it as ValidateForeignKey.
    op = ValidateForeignKey(model_name=MODEL_NAME, name="tfk")
    name, args, kwargs = op.deconstruct()

    assert name == "ValidateForeignKey"
    assert ValidateForeignKey(**kwargs).deconstruct() == op.deconstruct()
