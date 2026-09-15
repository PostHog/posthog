"""Functional tests for SafeDropTable.

Each test builds real tables with real Django-shaped foreign keys, so the catalog lookups
that decide the lock list run against the same pg_constraint and pg_inherits rows a
migration would see.
"""

import re
import uuid

import pytest

from django.db import connection
from django.db.migrations.writer import OperationWriter

from posthog.migration_helpers import SafeDropTable


@pytest.fixture
def temp_tables():
    suffix = uuid.uuid4().hex[:8]
    parent = f"test_safedrop_parent_{suffix}"
    child_a = f"test_safedrop_child_a_{suffix}"
    child_b = f"test_safedrop_child_b_{suffix}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE "{parent}" (id serial primary key)')
        for child in (child_a, child_b):
            cursor.execute(
                f"""
                CREATE TABLE "{child}" (
                    id serial primary key,
                    owner_id int REFERENCES "{parent}"(id) DEFERRABLE INITIALLY DEFERRED
                )
                """
            )
    try:
        yield child_a, child_b, parent
    finally:
        with connection.cursor() as cursor:
            for table in (child_a, child_b, parent):
                cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


@pytest.fixture
def partitioned_tables():
    suffix = uuid.uuid4().hex[:8]
    root = f"test_safedrop_partitioned_{suffix}"
    leaf = f"{root}_default"
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE "{root}" (
                id serial,
                created_at timestamptz NOT NULL,
                PRIMARY KEY (id, created_at)
            ) PARTITION BY RANGE (created_at)
            """
        )
        cursor.execute(f'CREATE TABLE "{leaf}" PARTITION OF "{root}" DEFAULT')
    try:
        yield root, leaf
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{root}" CASCADE')


def _apply(op, collect=False):
    schema_editor = connection.schema_editor(atomic=False, collect_sql=collect)
    schema_editor.__enter__()
    try:
        op.database_forwards("posthog", schema_editor, from_state=None, to_state=None)
    finally:
        schema_editor.__exit__(None, None, None)
    return schema_editor.collected_sql if collect else None


def _tables_exist(*tables):
    with connection.cursor() as cursor:
        cursor.execute("SELECT relname FROM pg_class WHERE relname = ANY(%s) AND relkind IN ('r', 'p')", [list(tables)])
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
def test_locks_the_referenced_parent_before_dropping(temp_tables):
    child_a, child_b, parent = temp_tables

    collected = _apply(collect=True, op=SafeDropTable([child_a, child_b]))

    lock = next(statement for statement in collected if "LOCK TABLE" in statement)
    drop = next(statement for statement in collected if "DROP TABLE" in statement)
    assert collected.index(lock) < collected.index(drop)
    for table in (child_a, child_b, parent):
        assert table in lock


@pytest.mark.django_db
def test_the_lock_phase_gives_up_before_any_deadlock_detector_runs(temp_tables):
    child_a, _, _ = temp_tables
    with connection.cursor() as cursor:
        cursor.execute("SELECT setting::int FROM pg_settings WHERE name = 'deadlock_timeout'")
        deadlock_ms = cursor.fetchone()[0]

    collected = _apply(collect=True, op=SafeDropTable(child_a))

    budgets = [int(match) for match in re.findall(r"SET LOCAL \w+_timeout = '(\d+)ms'", "\n".join(collected))]
    assert len(budgets) == 2  # lock_timeout bounds one attempt, statement_timeout bounds them all
    assert all(0 < budget < deadlock_ms for budget in budgets)


@pytest.mark.django_db
def test_restores_the_timeouts_the_transaction_came_in_with(temp_tables):
    # ValidateConstraint disables both timeouts for the rest of its transaction. Restoring
    # to DEFAULT rather than to the captured value would silently re-arm them.
    child_a, _, _ = temp_tables
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('statement_timeout', '0', true)")
        cursor.execute("SELECT set_config('lock_timeout', '17s', true)")

    _apply(SafeDropTable(child_a))

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")
        assert cursor.fetchone() == ("17s", "0")


@pytest.mark.django_db
def test_drops_every_named_table(temp_tables):
    child_a, child_b, parent = temp_tables

    _apply(SafeDropTable([child_a, child_b]))

    assert _tables_exist(child_a, child_b, parent) == {parent}


@pytest.mark.django_db
def test_a_second_run_is_a_no_op(temp_tables):
    child_a, child_b, _ = temp_tables
    op = SafeDropTable([child_a, child_b])

    _apply(op)
    _apply(op)

    assert _tables_exist(child_a, child_b) == set()


@pytest.mark.django_db
@pytest.mark.parametrize("target", ["root", "leaf"])
def test_refuses_a_table_whose_hierarchy_the_lock_list_misses(partitioned_tables, target):
    # The root carries relkind 'p', so the existence query cannot see it and a silent return
    # would record the migration with the table still there. The leaf is an ordinary table,
    # but its inheritance parent is no foreign-key target, so nothing puts that parent in the
    # lock list and the drop takes ACCESS EXCLUSIVE on it while the statement runs.
    root, leaf = partitioned_tables

    with pytest.raises(RuntimeError, match="whole hierarchy in the lock list"):
        _apply(SafeDropTable(root if target == "root" else leaf))

    assert _tables_exist(root, leaf) == {root, leaf}


def test_the_drop_cannot_be_reversed():
    op = SafeDropTable("test_safedrop_child")

    # Migration.unapply checks the flag and never reaches database_backwards.
    assert op.reversible is False
    with pytest.raises(NotImplementedError, match="irreversible"):
        op.database_backwards("posthog", None, None, None)


def test_needs_a_table():
    with pytest.raises(ValueError, match="at least one table"):
        SafeDropTable([])


@pytest.mark.parametrize("tables", ["test_safedrop_child", ["test_safedrop_child_a", "test_safedrop_child_b"]])
def test_the_migration_writer_can_rebuild_the_operation(tables):
    # squashmigrations renders every operation through this writer, and the writer maps each
    # captured argument onto a constructor parameter name. A `*tables` signature offers no
    # name, so it raises IndexError, and a deconstruct that only emits kwargs renders
    # SafeDropTable() with the tables silently gone.
    op = SafeDropTable(tables)

    rendered, _ = OperationWriter(op, indentation=0).serialize()

    assert f"tables={tables!r}" in rendered
    _, args, kwargs = op.deconstruct()
    assert SafeDropTable(*args, **kwargs).tables == op.tables
