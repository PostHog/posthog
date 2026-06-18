"""Idempotent CREATE/DROP INDEX CONCURRENTLY operations for Django migrations.

The Django built-ins (`AddIndexConcurrently`, `RemoveIndexConcurrently`) emit
bare `CREATE/DROP INDEX CONCURRENTLY` with no `IF [NOT] EXISTS`, and there is
no hook to disable `lock_timeout` / `statement_timeout`. Under bin/migrate's
exponential-backoff retry loop, a single transient timeout cancellation
leaves an INVALID index in pg_class and every subsequent retry then fails
with "relation already exists". Adding `IF NOT EXISTS` is only a partial
fix — it skips on name collision but does not detect that the leftover
index is invalid (indisvalid = false), so the migration is marked applied
while the index quietly does nothing.

These helpers implement the same recovery pattern GitLab uses in
`add_concurrent_index` / `remove_concurrent_index`:

1. Disable `lock_timeout` and `statement_timeout` on this connection so
   deploy-time timeouts can't cancel the build.
2. Look the index up in pg_class/pg_index. If it exists with
   indisvalid = false, DROP it first — recovering from a prior interrupted
   build, and emitting a structured log line so the recovery is visible
   in the deploy log (otherwise the auto-recovery would silently mask
   repeated cancellations).
3. Run the CREATE/DROP statement so retries are safe.

There are two flavors:

`SafeAddIndexConcurrently` / `SafeRemoveIndexConcurrently` (preferred) take a
`model_name` + Django `Index`, exactly like Django's own
`AddIndexConcurrently` / `RemoveIndexConcurrently`. They track Django state
themselves, so there is no `SeparateDatabaseAndState` wrapper and no
re-specifying the index as raw SQL:

    operations = [
        SafeAddIndexConcurrently(
            model_name="mymodel",
            index=models.Index(fields=["team", "-created_at"], name="my_idx"),
        ),
    ]

`CreateIndexConcurrently` / `DropIndexConcurrently` take the raw index SQL
(`index_name`, `table_name`, `columns`). They subclass `RunSQL`, which does
not touch Django state, so they must be wrapped in `SeparateDatabaseAndState`
with a matching `AddIndex` / `RemoveIndex`. Reach for these only when the
index doesn't map cleanly to a Django `Index` (e.g. an expression the ORM
can't model):

    migrations.SeparateDatabaseAndState(
        state_operations=[migrations.AddIndex(...)],
        database_operations=[CreateIndexConcurrently(
            index_name="my_idx",
            table_name="my_table",
            columns="(col_a, col_b)",
        )],
    )

The Migration class still needs `atomic = False`.
"""

from django.contrib.postgres.operations import AddIndexConcurrently, RemoveIndexConcurrently
from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def _disable_timeouts(schema_editor) -> None:
    schema_editor.execute("SET lock_timeout = 0")
    schema_editor.execute("SET statement_timeout = 0")


def _index_validity(schema_editor, index_name: str) -> str | None:
    """None if no index of this name exists, else "valid" or "invalid" (indisvalid)."""
    with schema_editor.connection.cursor() as cursor:
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
        if row is None:
            return None
        return "valid" if row[0] else "invalid"


def _log_and_drop_invalid_index(schema_editor, index_name: str, op_name: str) -> None:
    """Drop an index left invalid by a prior interrupted CONCURRENTLY build.

    The caller has already established (via `_index_validity`) that the index
    is invalid - Postgres left the row in pg_class with indisvalid = false after
    a build was cancelled mid-flight (OOM, pod kill, lock_timeout, etc.), and a
    plain `CREATE INDEX CONCURRENTLY IF NOT EXISTS` would silently skip past it.

    The recovery is intentionally noisy: a log line plus a migration stdout
    message, both tagged with the index name. Without this, the auto-recovery
    would mask repeated cancellations of the same index and we would never
    know a table has chronic lock contention or memory pressure during builds.
    """
    logger.warning(
        "concurrent_index_recovering_from_invalid_leftover",
        index_name=index_name,
        operation=op_name,
    )
    # Mirror to migration stdout so it shows up in bin/migrate log,
    # not just the application log stream.
    print(  # noqa: T201
        f"[{op_name}] index {index_name!r} was left in an "
        "invalid state by a prior interrupted build; dropping and "
        "rebuilding it. If this fires repeatedly for the same index, "
        "investigate why the prior build was cancelled."
    )
    schema_editor.execute(_build_drop_sql(index_name))


def _build_create_sql(
    *,
    index_name: str,
    table_name: str,
    columns: str,
    unique: bool,
    using: str,
    where: str,
) -> str:
    unique_kw = "UNIQUE " if unique else ""
    using_kw = f" USING {using}" if using else ""
    where_kw = f" {where}" if where else ""
    return (
        f'CREATE {unique_kw}INDEX CONCURRENTLY IF NOT EXISTS "{index_name}" '
        f'ON "{table_name}"{using_kw} {columns}{where_kw}'
    )


def _build_drop_sql(index_name: str) -> str:
    return f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"'


class _ConcurrentIndexOp(migrations.RunSQL):
    """Shared machinery for CREATE/DROP INDEX CONCURRENTLY.

    Inherits from RunSQL so sqlmigrate / introspection still show meaningful
    SQL; the real apply path is overridden in `database_forwards` /
    `database_backwards`.
    """

    reversible = True

    # Set by subclass __init__; read by deconstruct() (so squashmigrations /
    # the migration writer can rebuild the op) and describe().
    index_name: str
    table_name: str
    columns: str
    unique: bool
    using: str
    where: str

    def deconstruct(self) -> tuple[str, list[object], dict[str, str | bool]]:
        # RunSQL.deconstruct() emits sql=/reverse_sql= kwargs, which this op's
        # keyword-only __init__ rejects — so squashmigrations / the migration
        # writer would fail to rebuild it. Emit the real constructor kwargs.
        kwargs: dict[str, str | bool] = {
            "index_name": self.index_name,
            "table_name": self.table_name,
            "columns": self.columns,
        }
        if self.unique:
            kwargs["unique"] = True
        if self.using:
            kwargs["using"] = self.using
        if self.where:
            kwargs["where"] = self.where
        return (self.__class__.__qualname__, [], kwargs)


class CreateIndexConcurrently(_ConcurrentIndexOp):
    """Idempotent CREATE INDEX CONCURRENTLY with invalid-index recovery.

    Arguments:
        index_name: name of the index to create. Required (used for the
            indisvalid check and the IF NOT EXISTS guard).
        table_name: target table.
        columns: column expression(s) including the surrounding parens,
            e.g. `"(team_id, slot_index)"` or `"(lower(email))"`.
        unique: emit `CREATE UNIQUE INDEX CONCURRENTLY`.
        using: index method, e.g. `"gin"`. Default is btree.
        where: partial-index predicate, including the `WHERE` keyword,
            e.g. `"WHERE deleted_at IS NULL"`. Empty by default.
    """

    def __init__(
        self,
        *,
        index_name: str,
        table_name: str,
        columns: str,
        unique: bool = False,
        using: str = "",
        where: str = "",
    ) -> None:
        # All constructor args survive on the instance: index_name/table_name
        # are read by `describe`, and every arg is needed by `deconstruct` so
        # squashmigrations can rebuild the op.
        self.index_name = index_name
        self.table_name = table_name
        self.columns = columns
        self.unique = unique
        self.using = using
        self.where = where
        super().__init__(
            sql=_build_create_sql(
                index_name=index_name,
                table_name=table_name,
                columns=columns,
                unique=unique,
                using=using,
                where=where,
            ),
            reverse_sql=_build_drop_sql(index_name),
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        _disable_timeouts(schema_editor)
        if _index_validity(schema_editor, self.index_name) == "invalid":
            _log_and_drop_invalid_index(schema_editor, self.index_name, type(self).__name__)
        schema_editor.execute(self.sql)  # CREATE ... IF NOT EXISTS

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        _disable_timeouts(schema_editor)
        schema_editor.execute(self.reverse_sql)

    def describe(self) -> str:
        return f"Concurrently create index {self.index_name} on {self.table_name}"


class DropIndexConcurrently(_ConcurrentIndexOp):
    """Idempotent DROP INDEX CONCURRENTLY.

    The forward direction has no invalid-leftover failure mode to recover
    from (DROP either succeeds or the index is missing). The reverse,
    however, is a CREATE INDEX CONCURRENTLY and needs the full recovery
    path — the same arguments as `CreateIndexConcurrently` (columns,
    unique, using, where) are required so the reverse can rebuild the
    same index shape.

    Arguments:
        index_name: name of the index to drop.
        table_name: target table (used for the reverse CREATE).
        columns: column expression(s) including parens (used for the
            reverse CREATE).
        unique / using / where: as in `CreateIndexConcurrently` (used for
            the reverse CREATE).
    """

    def __init__(
        self,
        *,
        index_name: str,
        table_name: str,
        columns: str,
        unique: bool = False,
        using: str = "",
        where: str = "",
    ) -> None:
        # All constructor args survive on the instance: index_name/table_name
        # are read on rollback / by `describe`, and every arg is needed by
        # `deconstruct` so squashmigrations can rebuild the op.
        self.index_name = index_name
        self.table_name = table_name
        self.columns = columns
        self.unique = unique
        self.using = using
        self.where = where
        super().__init__(
            sql=_build_drop_sql(index_name),
            reverse_sql=_build_create_sql(
                index_name=index_name,
                table_name=table_name,
                columns=columns,
                unique=unique,
                using=using,
                where=where,
            ),
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        _disable_timeouts(schema_editor)
        schema_editor.execute(self.sql)

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        _disable_timeouts(schema_editor)
        if _index_validity(schema_editor, self.index_name) == "invalid":
            _log_and_drop_invalid_index(schema_editor, self.index_name, type(self).__name__)
        schema_editor.execute(self.reverse_sql)  # CREATE ... IF NOT EXISTS

    def describe(self) -> str:
        return f"Concurrently drop index {self.index_name} on {self.table_name}"


class SafeAddIndexConcurrently(AddIndexConcurrently):
    """State-aware CREATE INDEX CONCURRENTLY with invalid-index recovery.

    The model-aware counterpart to `CreateIndexConcurrently`: pass the same
    `model_name` + `Index` you would give Django's `AddIndexConcurrently`, and
    this op tracks Django state itself (no `SeparateDatabaseAndState` wrapper,
    no re-specifying the columns as raw SQL) while adding the safety the bare
    Django op lacks:

    - disables lock_timeout / statement_timeout so a deploy-time timeout can't
      cancel the build,
    - skips when a valid index of that name already exists (idempotent retry),
    - drops and rebuilds an indisvalid = false leftover from a prior
      interrupted build, logging a breadcrumb so the recovery is visible.

    Prefer this for the common case. Drop down to `CreateIndexConcurrently`
    only when the index doesn't map to a Django `Index`.

        operations = [
            SafeAddIndexConcurrently(
                model_name="mymodel",
                index=models.Index(fields=["team", "-created_at"], name="my_idx"),
            ),
        ]

    The Migration class still needs `atomic = False`.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        self._ensure_not_in_transaction(schema_editor)
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        _disable_timeouts(schema_editor)
        validity = _index_validity(schema_editor, self.index.name)
        if validity == "valid":
            return  # already built; a bin/migrate retry is a no-op
        if validity == "invalid":
            _log_and_drop_invalid_index(schema_editor, self.index.name, type(self).__name__)
        schema_editor.add_index(model, self.index, concurrently=True)

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        self._ensure_not_in_transaction(schema_editor)
        model = from_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        _disable_timeouts(schema_editor)
        if _index_validity(schema_editor, self.index.name) is None:
            return  # already dropped; a bin/migrate retry is a no-op
        schema_editor.remove_index(model, self.index, concurrently=True)


class SafeRemoveIndexConcurrently(RemoveIndexConcurrently):
    """State-aware DROP INDEX CONCURRENTLY, the reverse of `SafeAddIndexConcurrently`.

    Pass `model_name` + the index name, like Django's `RemoveIndexConcurrently`.
    Forward drops the index (skipping if already gone); reverse rebuilds it with
    the same timeout-disabling + invalid-leftover recovery as
    `SafeAddIndexConcurrently`. The Migration class still needs `atomic = False`.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state) -> None:
        self._ensure_not_in_transaction(schema_editor)
        model = from_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        _disable_timeouts(schema_editor)
        if _index_validity(schema_editor, self.name) is None:
            return  # already dropped; a bin/migrate retry is a no-op
        from_model_state = from_state.models[app_label, self.model_name_lower]
        index = from_model_state.get_index_by_name(self.name)
        schema_editor.remove_index(model, index, concurrently=True)

    def database_backwards(self, app_label, schema_editor, from_state, to_state) -> None:
        self._ensure_not_in_transaction(schema_editor)
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        _disable_timeouts(schema_editor)
        validity = _index_validity(schema_editor, self.name)
        if validity == "valid":
            return  # already rebuilt; a bin/migrate retry is a no-op
        if validity == "invalid":
            _log_and_drop_invalid_index(schema_editor, self.name, type(self).__name__)
        to_model_state = to_state.models[app_label, self.model_name_lower]
        index = to_model_state.get_index_by_name(self.name)
        schema_editor.add_index(model, index, concurrently=True)
