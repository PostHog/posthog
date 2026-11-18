"""Functional tests for the concurrent-index helpers.

Each test creates and drops a real table inside the standard test database
so we can poke pg_index.indisvalid directly and assert the helper's
recovery path. The table name is unique per test run to avoid colliding
with anything else in the schema.
"""

import uuid

import pytest
from unittest.mock import patch

from django.db import connection, migrations, models, router
from django.db.migrations.state import ModelState, ProjectState

from posthog.migration_helpers import (
    CreateIndexConcurrently,
    DropFieldIndexesConcurrently,
    DropIndexConcurrently,
    SafeAddIndexConcurrently,
    SafeRemoveIndexConcurrently,
)


@pytest.fixture
def temp_table():
    """Create a one-off table and drop it on teardown."""
    name = f"test_cic_{uuid.uuid4().hex[:8]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE "{name}" (id serial primary key, col int)')
    try:
        yield name
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{name}"')


def _apply(op):
    """Run a migration op forwards against the real connection."""
    schema_editor = connection.schema_editor(atomic=False)
    schema_editor.__enter__()
    try:
        op.database_forwards("posthog", schema_editor, from_state=None, to_state=None)
    finally:
        schema_editor.__exit__(None, None, None)


def _index_exists(index_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_class WHERE relname = %s", [index_name])
        return cursor.fetchone() is not None


def _index_is_valid(index_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT i.indisvalid
            FROM pg_class c
            JOIN pg_index i ON c.oid = i.indexrelid
            WHERE c.relname = %s
            """,
            [index_name],
        )
        row = cursor.fetchone()
        return bool(row and row[0])


@pytest.mark.django_db(transaction=True)
def test_create_index_concurrently_creates_index(temp_table):
    idx_name = f"{temp_table}_col_idx"
    op = CreateIndexConcurrently(index_name=idx_name, table_name=temp_table, columns="(col)")

    _apply(op)

    assert _index_exists(idx_name)
    assert _index_is_valid(idx_name)


@pytest.mark.django_db(transaction=True)
def test_create_index_concurrently_is_idempotent(temp_table):
    """Second apply must not raise — IF NOT EXISTS skips the existing valid index."""
    idx_name = f"{temp_table}_col_idx"
    op = CreateIndexConcurrently(index_name=idx_name, table_name=temp_table, columns="(col)")

    _apply(op)
    _apply(op)

    assert _index_is_valid(idx_name)


@pytest.mark.django_db(transaction=True)
def test_create_index_concurrently_recovers_from_invalid_leftover(temp_table, capsys):
    """Plant an invalid index, then run the helper; it should drop and rebuild.

    Also asserts the recovery is *noisy* — the auto-recovery would otherwise
    mask repeated cancellations of the same index, so a stdout breadcrumb is
    a hard requirement, not nice-to-have.
    """
    idx_name = f"{temp_table}_col_idx"

    # Fake an interrupted CONCURRENTLY build by inserting an invalid index row.
    # Postgres only lets you do this via CREATE INDEX with a deliberately
    # poisoned predicate that fails after the catalog row is laid down — the
    # cleanest portable way is to mark a freshly-built index invalid by hand.
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE INDEX "{idx_name}" ON "{temp_table}" (col)')
        cursor.execute(
            """
            UPDATE pg_index SET indisvalid = false
            WHERE indexrelid = (SELECT oid FROM pg_class WHERE relname = %s)
            """,
            [idx_name],
        )

    assert _index_exists(idx_name)
    assert not _index_is_valid(idx_name)

    op = CreateIndexConcurrently(index_name=idx_name, table_name=temp_table, columns="(col)")
    _apply(op)

    assert _index_exists(idx_name)
    assert _index_is_valid(idx_name)

    captured = capsys.readouterr()
    assert "invalid state by a prior interrupted build" in captured.out
    assert idx_name in captured.out


@pytest.mark.django_db(transaction=True)
def test_no_recovery_breadcrumb_when_no_invalid_leftover(temp_table, capsys):
    """Conversely, a clean first-time apply must NOT print the recovery
    breadcrumb. We only want noise when something was actually recovered.
    """
    idx_name = f"{temp_table}_col_idx"
    op = CreateIndexConcurrently(index_name=idx_name, table_name=temp_table, columns="(col)")
    _apply(op)

    captured = capsys.readouterr()
    assert "invalid state by a prior interrupted build" not in captured.out


@pytest.mark.django_db(transaction=True)
def test_create_index_concurrently_unique_partial_with_using(temp_table):
    idx_name = f"{temp_table}_uniq_idx"
    op = CreateIndexConcurrently(
        index_name=idx_name,
        table_name=temp_table,
        columns="(col)",
        unique=True,
        using="btree",
        where="WHERE col IS NOT NULL",
    )

    _apply(op)

    assert _index_is_valid(idx_name)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
            [idx_name],
        )
        indexdef = cursor.fetchone()[0]
    assert "UNIQUE" in indexdef
    assert "WHERE" in indexdef


@pytest.mark.django_db(transaction=True)
def test_drop_index_concurrently_removes_index(temp_table):
    idx_name = f"{temp_table}_col_idx"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE INDEX "{idx_name}" ON "{temp_table}" (col)')
    assert _index_exists(idx_name)

    op = DropIndexConcurrently(index_name=idx_name, table_name=temp_table, columns="(col)")
    _apply(op)

    assert not _index_exists(idx_name)


@pytest.mark.django_db(transaction=True)
def test_drop_index_concurrently_is_idempotent(temp_table):
    """Running drop when the index is already gone must not raise."""
    idx_name = f"{temp_table}_col_idx"
    op = DropIndexConcurrently(index_name=idx_name, table_name=temp_table, columns="(col)")

    _apply(op)  # nothing to drop the first time
    _apply(op)  # still nothing the second time

    assert not _index_exists(idx_name)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("op_cls,index_present", [(CreateIndexConcurrently, False), (DropIndexConcurrently, True)])
def test_raw_ops_skip_a_database_the_router_excludes(temp_table, op_cls, index_present):
    idx_name = f"{temp_table}_col_idx"
    if index_present:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE INDEX "{idx_name}" ON "{temp_table}" (col)')
    op = op_cls(index_name=idx_name, table_name=temp_table, columns="(col)")

    with patch.object(router, "allow_migrate", return_value=False):
        _apply(op)

    assert _index_exists(idx_name) == index_present


@pytest.mark.django_db(transaction=True)
def test_subclasses_runsql_for_introspection_compatibility():
    """Subclasses must remain RunSQL so makemigrations / sqlmigrate continue to work."""
    op = CreateIndexConcurrently(index_name="x", table_name="y", columns="(z)")
    assert isinstance(op, migrations.RunSQL)
    # RunSQL types sql/reverse_sql as str | Sequence | None; the helper always
    # builds plain strings, so narrow before the membership checks.
    assert isinstance(op.sql, str)
    assert isinstance(op.reverse_sql, str)
    assert "CREATE INDEX CONCURRENTLY" in op.sql
    assert "IF NOT EXISTS" in op.sql
    assert "DROP INDEX CONCURRENTLY" in op.reverse_sql
    assert "IF EXISTS" in op.reverse_sql


@pytest.mark.parametrize("op_cls", [CreateIndexConcurrently, DropIndexConcurrently])
@pytest.mark.parametrize(
    "extra_kwargs",
    [
        {},
        {"unique": True, "using": "btree", "where": "WHERE col_a IS NOT NULL"},
    ],
)
def test_deconstruct_round_trips(op_cls, extra_kwargs):
    # RunSQL.deconstruct() emits sql=/reverse_sql=, which the helper __init__
    # rejects; the override must emit kwargs that rebuild an equivalent op so
    # squashmigrations / the migration writer work.
    op = op_cls(index_name="my_idx", table_name="my_table", columns="(col_a)", **extra_kwargs)

    name, args, kwargs = op.deconstruct()

    assert name == op_cls.__name__
    assert args == []
    rebuilt = op_cls(**kwargs)
    assert rebuilt.sql == op.sql
    assert rebuilt.reverse_sql == op.reverse_sql


# --- State-aware helpers: SafeAddIndexConcurrently / SafeRemoveIndexConcurrently ---

MODEL_NAME = "TempSciModel"
MODEL_NAME_LOWER = "tempscimodel"


@pytest.fixture
def temp_model():
    """A one-off table plus a ProjectState model pointing at it.

    The state-aware ops resolve the model + index from migration state
    (unlike the raw-SQL helpers), so the test has to hand them a real state.
    """
    table = f"test_sci_{uuid.uuid4().hex[:8]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE "{table}" (id serial primary key, col int)')
    state = ProjectState()
    state.add_model(
        ModelState(
            app_label="posthog",
            name=MODEL_NAME,
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("col", models.IntegerField(null=True)),
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


def test_safe_add_index_tracks_state_without_separate_database_and_state():
    """The whole point of the state-aware helper: state_forwards updates Django
    model state on its own, so no SeparateDatabaseAndState wrapper is needed.
    """
    state = ProjectState()
    state.add_model(
        ModelState(
            app_label="posthog",
            name=MODEL_NAME,
            fields=[("id", models.AutoField(primary_key=True)), ("col", models.IntegerField(null=True))],
        )
    )
    index = models.Index(fields=["col"], name="state_tracking_idx")
    op = SafeAddIndexConcurrently(model_name=MODEL_NAME, index=index)

    new_state = state.clone()
    op.state_forwards("posthog", new_state)

    assert new_state.models["posthog", MODEL_NAME_LOWER].get_index_by_name("state_tracking_idx") == index


@pytest.mark.django_db(transaction=True)
def test_safe_add_index_concurrently_creates_index(temp_model):
    table, state = temp_model
    idx_name = f"{table}_col_idx"
    op = SafeAddIndexConcurrently(model_name=MODEL_NAME, index=models.Index(fields=["col"], name=idx_name))

    _apply_forwards(op, state)

    assert _index_exists(idx_name)
    assert _index_is_valid(idx_name)


@pytest.mark.django_db(transaction=True)
def test_safe_add_index_concurrently_is_idempotent(temp_model):
    """Second apply skips on the already-valid index instead of raising."""
    table, state = temp_model
    idx_name = f"{table}_col_idx"
    op = SafeAddIndexConcurrently(model_name=MODEL_NAME, index=models.Index(fields=["col"], name=idx_name))

    _apply_forwards(op, state)
    _apply_forwards(op, state)

    assert _index_is_valid(idx_name)


@pytest.mark.django_db(transaction=True)
def test_safe_add_index_concurrently_recovers_from_invalid_leftover(temp_model, capsys):
    table, state = temp_model
    idx_name = f"{table}_col_idx"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE INDEX "{idx_name}" ON "{table}" (col)')
        cursor.execute(
            """
            UPDATE pg_index SET indisvalid = false
            WHERE indexrelid = (SELECT oid FROM pg_class WHERE relname = %s)
            """,
            [idx_name],
        )
    assert _index_exists(idx_name)
    assert not _index_is_valid(idx_name)

    op = SafeAddIndexConcurrently(model_name=MODEL_NAME, index=models.Index(fields=["col"], name=idx_name))
    _apply_forwards(op, state)

    assert _index_is_valid(idx_name)
    captured = capsys.readouterr()
    assert "invalid state by a prior interrupted build" in captured.out
    assert idx_name in captured.out


@pytest.mark.django_db(transaction=True)
def test_safe_add_index_concurrently_partial_descending(temp_model):
    """Delegating to schema_editor.add_index covers index shapes the raw-SQL
    helper would force you to hand-translate (ordering, partial predicate).
    """
    table, state = temp_model
    idx_name = f"{table}_partial_idx"
    op = SafeAddIndexConcurrently(
        model_name=MODEL_NAME,
        index=models.Index(fields=["-col"], name=idx_name, condition=models.Q(col__isnull=False)),
    )

    _apply_forwards(op, state)

    assert _index_is_valid(idx_name)
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname = %s", [idx_name])
        indexdef = cursor.fetchone()[0]
    assert "DESC" in indexdef
    assert "WHERE" in indexdef


@pytest.mark.django_db(transaction=True)
def test_safe_add_index_concurrently_reverse_drops_index(temp_model):
    table, state = temp_model
    idx_name = f"{table}_col_idx"
    op = SafeAddIndexConcurrently(model_name=MODEL_NAME, index=models.Index(fields=["col"], name=idx_name))

    _apply_forwards(op, state)
    assert _index_exists(idx_name)

    _apply_backwards(op, state)
    assert not _index_exists(idx_name)

    _apply_backwards(op, state)  # idempotent: nothing left to drop
    assert not _index_exists(idx_name)


@pytest.mark.django_db(transaction=True)
def test_safe_remove_index_concurrently_removes_index(temp_model):
    table, state = temp_model
    idx_name = f"{table}_col_idx"
    # Register the index in state (so RemoveIndex can resolve it), then build it.
    add = SafeAddIndexConcurrently(model_name=MODEL_NAME, index=models.Index(fields=["col"], name=idx_name))
    add.state_forwards("posthog", state)
    _apply_forwards(add, state)
    assert _index_exists(idx_name)

    remove = SafeRemoveIndexConcurrently(model_name=MODEL_NAME, name=idx_name)
    _apply_forwards(remove, state)
    assert not _index_exists(idx_name)

    _apply_forwards(remove, state)  # idempotent: already gone
    assert not _index_exists(idx_name)


@pytest.mark.django_db(transaction=True)
def test_safe_remove_index_concurrently_reverse_recreates(temp_model):
    table, state = temp_model
    idx_name = f"{table}_col_idx"
    add = SafeAddIndexConcurrently(model_name=MODEL_NAME, index=models.Index(fields=["col"], name=idx_name))
    add.state_forwards("posthog", state)
    _apply_forwards(add, state)

    remove = SafeRemoveIndexConcurrently(model_name=MODEL_NAME, name=idx_name)
    _apply_forwards(remove, state)
    assert not _index_exists(idx_name)

    _apply_backwards(remove, state)  # reverse of a drop rebuilds the index
    assert _index_is_valid(idx_name)


@pytest.mark.parametrize(
    "op",
    [
        SafeAddIndexConcurrently(model_name=MODEL_NAME, index=models.Index(fields=["col"], name="i")),
        SafeRemoveIndexConcurrently(model_name=MODEL_NAME, name="i"),
    ],
)
def test_safe_ops_deconstruct_round_trips(op):
    """Unlike the RunSQL-based helpers, these inherit Django's deconstruct;
    confirm it emits the model_name/index kwargs the migration writer needs.
    """
    name, args, kwargs = op.deconstruct()

    assert name == type(op).__name__
    assert args == []
    rebuilt = type(op)(**kwargs)
    assert rebuilt.deconstruct() == op.deconstruct()


# --- DropFieldIndexesConcurrently ---


@pytest.fixture
def key_tables():
    """Table names for a parent and a child with a foreign key, dropped on teardown."""
    suffix = uuid.uuid4().hex[:8]
    parent, child = f"test_fkp_{suffix}", f"test_fkc_{suffix}"
    try:
        yield parent, child
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{child}", "{parent}"')


def _create_key_tables(
    parent: str,
    child: str,
    *,
    on_delete=models.CASCADE,
    db_constraint: bool = True,
    to_field: str | None = None,
    indexes: list[models.Index] | None = None,
    constraints: list[models.UniqueConstraint] | None = None,
) -> ProjectState:
    state = ProjectState()
    state.add_model(
        ModelState(
            app_label="posthog",
            name="TempFkParent",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("code", models.CharField(max_length=20, unique=True)),
            ],
            options={"db_table": parent},
        )
    )
    state.add_model(
        ModelState(
            app_label="posthog",
            name="TempFkChild",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                (
                    "owner",
                    models.ForeignKey(
                        "posthog.tempfkparent", on_delete=on_delete, db_constraint=db_constraint, to_field=to_field
                    ),
                ),
                ("seq", models.IntegerField(default=0)),
            ],
            options={"db_table": child, "indexes": indexes or [], "constraints": constraints or []},
        )
    )
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(state.apps.get_model("posthog", "TempFkParent"))
        schema_editor.create_model(state.apps.get_model("posthog", "TempFkChild"))
    return state


def _indexes_on_only(table: str, column: str) -> set[str]:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    return {name for name, info in constraints.items() if info["index"] and info["columns"] == [column]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "on_delete,db_constraint,to_field,index_fields,index_condition,conditional_unique",
    [
        pytest.param(
            models.CASCADE, True, None, ["owner", "seq"], None, False, id="another_index_leads_with_the_column"
        ),
        pytest.param(models.CASCADE, True, None, ["owner"], None, False, id="a_meta_index_on_the_same_column"),
        pytest.param(
            models.CASCADE,
            True,
            None,
            ["owner"],
            models.Q(owner__isnull=False),
            False,
            id="a_partial_index_that_skips_only_nulls",
        ),
        pytest.param(models.DO_NOTHING, False, None, None, None, False, id="no_parent_delete_reads_the_column"),
        pytest.param(models.CASCADE, True, "code", ["owner", "seq"], None, False, id="a_key_to_a_text_column"),
        pytest.param(models.CASCADE, True, None, ["owner", "seq"], None, True, id="a_conditional_unique_on_the_column"),
    ],
)
def test_drop_foreign_key_index_drops_only_the_automatic_indexes(
    key_tables, on_delete, db_constraint, to_field, index_fields, index_condition, conditional_unique
):
    parent, child = key_tables
    indexes = (
        [models.Index(fields=index_fields, condition=index_condition, name=f"{child}_meta")] if index_fields else []
    )
    constraints = (
        [models.UniqueConstraint(fields=["owner"], condition=models.Q(seq__gt=0), name=f"{child}_uniq")]
        if conditional_unique
        else []
    )
    state = _create_key_tables(
        parent,
        child,
        on_delete=on_delete,
        db_constraint=db_constraint,
        to_field=to_field,
        indexes=indexes,
        constraints=constraints,
    )
    single_column_meta = {index.name for index in indexes if index.fields == ["owner"]} | {
        constraint.name for constraint in constraints
    }
    automatic = _indexes_on_only(child, "owner_id") - single_column_meta
    op = DropFieldIndexesConcurrently(model_name="TempFkChild", name="owner")

    _apply_forwards(op, state)
    assert _indexes_on_only(child, "owner_id") == single_column_meta

    _apply_forwards(op, state)  # a bin/migrate retry finds nothing left to drop
    assert _indexes_on_only(child, "owner_id") == single_column_meta

    after = state.clone()
    op.state_forwards("posthog", after)
    assert after.models["posthog", "tempfkchild"].fields["owner"].db_index is False

    _apply_backwards(op, state)
    assert all(_index_is_valid(name) for name in automatic)
    assert _indexes_on_only(child, "owner_id") == automatic | single_column_meta


@pytest.mark.django_db(transaction=True)
def test_drop_field_indexes_drops_only_the_like_companion_of_a_unique_field(key_tables):
    parent, child = key_tables
    state = _create_key_tables(parent, child)
    (like,) = _indexes_on_only(parent, "code")
    op = DropFieldIndexesConcurrently(model_name="TempFkParent", name="code")
    before = state.models["posthog", "tempfkparent"].fields["code"].deconstruct()

    _apply_forwards(op, state)
    assert _indexes_on_only(parent, "code") == set()
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, parent)
    assert any(info["unique"] and info["columns"] == ["code"] for info in constraints.values())

    after = state.clone()
    op.state_forwards("posthog", after)
    assert after.models["posthog", "tempfkparent"].fields["code"].deconstruct() == before

    _apply_backwards(op, state)
    assert _indexes_on_only(parent, "code") == {like}
    assert _index_is_valid(like)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "on_delete,db_constraint,setup_sql,error",
    [
        pytest.param(
            models.CASCADE,
            True,
            'CREATE INDEX "{child}_stray" ON "{child}" (owner_id)',
            "Find out what created it",
            id="an_unexpected_index_on_the_column",
        ),
        pytest.param(models.CASCADE, True, None, "No other btree index", id="no_other_index_leads_with_the_column"),
        pytest.param(
            models.DO_NOTHING, True, None, "No other btree index", id="only_the_commit_check_reads_the_column"
        ),
        pytest.param(
            models.CASCADE, False, None, "No other btree index", id="only_the_delete_collector_reads_the_column"
        ),
        pytest.param(
            models.CASCADE,
            True,
            'DROP INDEX "{automatic}"',
            "No other btree index",
            id="the_automatic_index_is_already_gone",
        ),
        pytest.param(
            models.CASCADE,
            True,
            'CREATE INDEX "{child}_partial" ON "{child}" (owner_id, seq) WHERE owner_id IS NOT NULL AND seq > 0',
            "No other btree index",
            id="a_partial_index_that_skips_more_than_nulls",
        ),
        pytest.param(
            models.DO_NOTHING,
            False,
            'ALTER TABLE "{child}" ADD CONSTRAINT "{child}_fk" FOREIGN KEY (owner_id) REFERENCES "{parent}" (id) NOT VALID',
            "No other btree index",
            id="a_database_key_that_state_does_not_track",
        ),
    ],
)
def test_drop_foreign_key_index_refuses_and_keeps_the_indexes(key_tables, on_delete, db_constraint, setup_sql, error):
    parent, child = key_tables
    state = _create_key_tables(parent, child, on_delete=on_delete, db_constraint=db_constraint)
    (automatic,) = _indexes_on_only(child, "owner_id")
    if setup_sql:
        with connection.cursor() as cursor:
            cursor.execute(setup_sql.format(parent=parent, child=child, automatic=automatic))
    before = _indexes_on_only(child, "owner_id")
    op = DropFieldIndexesConcurrently(model_name="TempFkChild", name="owner")

    with pytest.raises(ValueError, match=error):
        _apply_forwards(op, state)

    assert _indexes_on_only(child, "owner_id") == before
