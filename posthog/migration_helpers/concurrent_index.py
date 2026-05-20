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
   build.
3. Run the CREATE/DROP statement with IF [NOT] EXISTS so retries are safe.

Wrap in SeparateDatabaseAndState so Django state still tracks the index:

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

from django.db import migrations


class _ConcurrentIndexOp(migrations.RunSQL):
    """Shared machinery for CREATE/DROP INDEX CONCURRENTLY.

    Inherits from RunSQL so sqlmigrate / introspection still show meaningful
    SQL; the real apply path is overridden in `database_forwards` /
    `database_backwards`.
    """

    reversible = True

    @staticmethod
    def _disable_timeouts(schema_editor) -> None:
        schema_editor.execute("SET lock_timeout = 0")
        schema_editor.execute("SET statement_timeout = 0")

    @staticmethod
    def _drop_if_invalid(schema_editor, index_name: str) -> None:
        """If `index_name` exists but is invalid, drop it.

        Recovers from a prior CONCURRENTLY build that was cancelled
        mid-flight (OOM, pod kill, lock_timeout, statement_timeout, etc.).
        Postgres leaves the row in pg_class with indisvalid = false; a
        plain `CREATE INDEX CONCURRENTLY IF NOT EXISTS` would silently
        skip and leave the invalid index in place.
        """
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM pg_class c
                JOIN pg_index i ON c.oid = i.indexrelid
                WHERE c.relname = %s AND NOT i.indisvalid
                """,
                [index_name],
            )
            if cursor.fetchone() is None:
                return
        schema_editor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"')


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
        self.index_name = index_name
        self.table_name = table_name
        self.columns = columns
        self.unique = unique
        self.using = using
        self.where = where

        unique_kw = "UNIQUE " if unique else ""
        using_kw = f" USING {using}" if using else ""
        where_kw = f" {where}" if where else ""

        sql = (
            f'CREATE {unique_kw}INDEX CONCURRENTLY IF NOT EXISTS "{index_name}" '
            f'ON "{table_name}"{using_kw} {columns}{where_kw}'
        )
        reverse_sql = f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"'
        super().__init__(sql=sql, reverse_sql=reverse_sql)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        self._disable_timeouts(schema_editor)
        self._drop_if_invalid(schema_editor, self.index_name)
        schema_editor.execute(self.sql)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        self._disable_timeouts(schema_editor)
        schema_editor.execute(self.reverse_sql)

    def describe(self) -> str:
        return f"Concurrently create index {self.index_name} on {self.table_name}"


class DropIndexConcurrently(_ConcurrentIndexOp):
    """Idempotent DROP INDEX CONCURRENTLY.

    The forward direction has no invalid-leftover failure mode to recover
    from (DROP either succeeds or the index is missing). The reverse,
    however, is a CREATE INDEX CONCURRENTLY and needs the full recovery
    path — passing `recreate_sql` plus the original index attributes
    enables that.

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
        self.index_name = index_name
        self.table_name = table_name
        self.columns = columns
        self.unique = unique
        self.using = using
        self.where = where

        unique_kw = "UNIQUE " if unique else ""
        using_kw = f" USING {using}" if using else ""
        where_kw = f" {where}" if where else ""

        sql = f'DROP INDEX CONCURRENTLY IF EXISTS "{index_name}"'
        reverse_sql = (
            f'CREATE {unique_kw}INDEX CONCURRENTLY IF NOT EXISTS "{index_name}" '
            f'ON "{table_name}"{using_kw} {columns}{where_kw}'
        )
        super().__init__(sql=sql, reverse_sql=reverse_sql)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        self._disable_timeouts(schema_editor)
        schema_editor.execute(self.sql)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        self._disable_timeouts(schema_editor)
        self._drop_if_invalid(schema_editor, self.index_name)
        schema_editor.execute(self.reverse_sql)

    def describe(self) -> str:
        return f"Concurrently drop index {self.index_name} on {self.table_name}"
