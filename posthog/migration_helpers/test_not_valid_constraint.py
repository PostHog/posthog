"""Functional tests for AddConstraintNotValid / ValidateConstraint.

Each test creates and drops a real table inside the standard test database so
we can poke pg_constraint.convalidated directly and exercise the two-phase
NOT VALID -> VALIDATE flow against live Postgres.
"""

import uuid

import pytest

from django.db import connection, models
from django.db.migrations.state import ModelState, ProjectState
from django.db.models import Q
from django.db.utils import IntegrityError

from posthog.migration_helpers import AddConstraintNotValid, ValidateConstraint

MODEL_NAME = "TmpCheckModel"
MODEL_NAME_LOWER = "tmpcheckmodel"


@pytest.fixture
def temp_model():
    """A one-off table plus a ProjectState model pointing at it."""
    table = f"test_nvc_{uuid.uuid4().hex[:8]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE "{table}" (id serial primary key, amount int)')
    state = ProjectState()
    state.add_model(
        ModelState(
            app_label="posthog",
            name=MODEL_NAME,
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("amount", models.IntegerField(null=True)),
            ],
            options={"db_table": table},
        )
    )
    try:
        yield table, state
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}"')


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
    """None if the constraint is absent, else its convalidated flag."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT convalidated FROM pg_constraint WHERE conname = %s", [constraint_name])
        row = cursor.fetchone()
        return None if row is None else bool(row[0])


def _insert(table, amount):
    with connection.cursor() as cursor:
        cursor.execute(f'INSERT INTO "{table}" (amount) VALUES (%s)', [amount])


def _check(name):
    return models.CheckConstraint(condition=Q(amount__gte=0), name=name)


def test_add_constraint_not_valid_rejects_non_check_constraint():
    with pytest.raises(ValueError, match="only supports CheckConstraint"):
        AddConstraintNotValid(model_name=MODEL_NAME, constraint=models.UniqueConstraint(fields=["amount"], name="u"))


def test_add_constraint_not_valid_tracks_state_without_separate_database_and_state():
    """state_forwards updates Django model state on its own (no SeparateDatabaseAndState)."""
    state = ProjectState()
    state.add_model(
        ModelState(
            app_label="posthog",
            name=MODEL_NAME,
            fields=[("id", models.AutoField(primary_key=True)), ("amount", models.IntegerField(null=True))],
        )
    )
    constraint = _check("state_tracking_chk")
    op = AddConstraintNotValid(model_name=MODEL_NAME, constraint=constraint)

    new_state = state.clone()
    op.state_forwards("posthog", new_state)

    constraints = new_state.models["posthog", MODEL_NAME_LOWER].options["constraints"]
    assert any(c.name == "state_tracking_chk" for c in constraints)


@pytest.mark.django_db(transaction=True)
def test_add_constraint_not_valid_creates_unvalidated_constraint(temp_model):
    table, state = temp_model
    name = f"{table}_amount_chk"
    op = AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check(name))

    _apply_forwards(op, state)

    assert _convalidated(name) is False  # present but not validated


@pytest.mark.django_db(transaction=True)
def test_add_constraint_not_valid_skips_existing_rows_but_enforces_new_rows(temp_model):
    """The point of NOT VALID: existing violations are tolerated, new ones aren't."""
    table, state = temp_model
    name = f"{table}_amount_chk"
    _insert(table, -5)  # pre-existing violation

    op = AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check(name))
    _apply_forwards(op, state)  # succeeds despite the violating row (no scan)

    with pytest.raises(IntegrityError):
        _insert(table, -1)  # new violation is rejected


@pytest.mark.django_db(transaction=True)
def test_add_constraint_not_valid_is_idempotent(temp_model):
    table, state = temp_model
    name = f"{table}_amount_chk"
    op = AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check(name))

    _apply_forwards(op, state)
    _apply_forwards(op, state)

    assert _convalidated(name) is False


@pytest.mark.django_db(transaction=True)
def test_add_constraint_not_valid_reverse_drops(temp_model):
    table, state = temp_model
    name = f"{table}_amount_chk"
    op = AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check(name))

    _apply_forwards(op, state)
    assert _convalidated(name) is False

    _apply_backwards(op, state)
    assert _convalidated(name) is None

    _apply_backwards(op, state)  # idempotent: DROP CONSTRAINT IF EXISTS
    assert _convalidated(name) is None


@pytest.mark.django_db(transaction=True)
def test_validate_constraint_marks_constraint_valid(temp_model):
    table, state = temp_model
    name = f"{table}_amount_chk"
    _insert(table, 5)  # clean data
    _apply_forwards(AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check(name)), state)
    assert _convalidated(name) is False

    _apply_forwards(ValidateConstraint(model_name=MODEL_NAME, name=name), state)

    assert _convalidated(name) is True


@pytest.mark.django_db(transaction=True)
def test_validate_constraint_is_idempotent(temp_model):
    table, state = temp_model
    name = f"{table}_amount_chk"
    _apply_forwards(AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check(name)), state)
    validate = ValidateConstraint(model_name=MODEL_NAME, name=name)

    _apply_forwards(validate, state)
    _apply_forwards(validate, state)  # already validated -> skipped

    assert _convalidated(name) is True


@pytest.mark.django_db(transaction=True)
def test_validate_constraint_fails_on_existing_violation(temp_model):
    table, state = temp_model
    name = f"{table}_amount_chk"
    _insert(table, -5)  # existing violation
    _apply_forwards(AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check(name)), state)

    with pytest.raises(IntegrityError):
        _apply_forwards(ValidateConstraint(model_name=MODEL_NAME, name=name), state)

    assert _convalidated(name) is False  # stays unvalidated, can retry after cleanup


@pytest.mark.django_db(transaction=True)
def test_validate_constraint_reverse_is_noop(temp_model):
    table, state = temp_model
    name = f"{table}_amount_chk"
    _apply_forwards(AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check(name)), state)
    validate = ValidateConstraint(model_name=MODEL_NAME, name=name)
    _apply_forwards(validate, state)

    _apply_backwards(validate, state)  # validation isn't reversible

    assert _convalidated(name) is True  # constraint untouched by the reverse


def _collected_forward_sql(op):
    """Run op.database_forwards in collect_sql mode and return the emitted SQL.

    collect_sql records statements instead of running them; the constraint is
    absent, so the validity probe returns None and the op proceeds to emit DDL.
    """
    state = ProjectState()
    state.add_model(
        ModelState(
            app_label="posthog",
            name=MODEL_NAME,
            fields=[("id", models.AutoField(primary_key=True)), ("amount", models.IntegerField(null=True))],
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
def test_validate_constraint_disables_timeouts():
    """VALIDATE scans the whole table under SHARE UPDATE EXCLUSIVE (no traffic
    block), so statement_timeout must be disabled or the scan is killed mid-flight
    and every bin/migrate retry repeats."""
    collected = _collected_forward_sql(ValidateConstraint(model_name=MODEL_NAME, name="tchk"))
    assert "SET lock_timeout = 0" in collected
    assert "SET statement_timeout = 0" in collected


@pytest.mark.django_db
def test_add_constraint_not_valid_keeps_lock_timeout():
    """NOT VALID is a brief metadata-only ALTER under ACCESS EXCLUSIVE, so it must
    keep the default lock_timeout and fail fast on contention rather than queue the
    lock behind in-flight queries and stall the table."""
    collected = _collected_forward_sql(AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check("tchk")))
    assert "SET lock_timeout = 0" not in collected
    assert "SET statement_timeout = 0" not in collected
    assert "ADD CONSTRAINT" in collected.upper()  # the op still emitted its DDL


@pytest.mark.parametrize(
    "op",
    [
        AddConstraintNotValid(model_name=MODEL_NAME, constraint=_check("c")),
        ValidateConstraint(model_name=MODEL_NAME, name="c"),
    ],
)
def test_deconstruct_round_trips(op):
    name, args, kwargs = op.deconstruct()

    assert name == type(op).__name__
    assert args == []
    rebuilt = type(op)(**kwargs)
    assert rebuilt.deconstruct() == op.deconstruct()
