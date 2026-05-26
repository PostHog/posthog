"""``profile_migrations`` contextmanager — per-op + per-SQL profiling.

The contextmanager monkeypatches three things for the lifetime of one
``migrate`` invocation and restores them on exit:

1. ``database_forwards`` on every concrete ``Operation`` subclass. Builds an
   ``OpRecord`` per op, pushes a frame onto the contextvar stack, times the
   call, and serializes the record on completion.
2. ``BaseDatabaseSchemaEditor.execute`` — captures every DDL statement emitted
   by ``CreateModel`` / ``AddIndex`` / ``RunSQL`` / etc. against the current
   op frame.
3. ``connection.execute_wrappers`` on every alias — captures cursor-level SQL
   from ``RunPython`` bodies (these bypass the schema editor entirely).
   The cursor wrapper checks ``frame.in_schema_editor_call`` to avoid
   double-counting DDL the schema editor already logged.

Frame attribution uses a ``ContextVar`` because Django's migrate path is sync
but executes inside ``atomic()`` blocks that may copy the context — contextvars
propagate cleanly across that.
"""

from __future__ import annotations

import sys
import json
import time
import socket
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import django
from django.conf import settings
from django.db import connections
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.migration import Migration
from django.db.migrations.operations.base import Operation

from posthog.management.migration_profiling.metadata import STATE_ONLY_OPERATIONS, extract
from posthog.management.migration_profiling.models import SCHEMA_VERSION, SQL_TRUNCATION_LIMIT, OpRecord, SqlRecord

MAX_SQL_PER_OP = 1000
PARAMS_REPR_LIMIT = 256


@dataclass
class _Frame:
    record: OpRecord
    monotonic_start: float
    in_schema_editor_call: bool = False
    sql_emitted: int = 0
    # Track which connection this op runs against so cross-DB cursor traffic
    # via routers can be excluded from attribution.
    target_connection_alias: str | None = None


@dataclass
class _ProfilerState:
    fp: IO[str]
    database: str
    truncation_limit: int | None
    bootstrap_sql: list[SqlRecord] = field(default_factory=list)
    bootstrap_started_at: str = ""
    bootstrap_monotonic_start: float = 0.0
    finalized_bootstrap: bool = False
    # Filled by the Migration.apply wrapper before each op runs.
    current_migration_app: str = "<unknown>"
    current_migration_name: str = "<unknown>"
    current_op_index: int = 0


_stack_var: ContextVar[list[_Frame]] = ContextVar("migration_profiler_stack")
_state_var: ContextVar[_ProfilerState | None] = ContextVar("migration_profiler_state", default=None)


# ---------- helpers ----------


def _get_stack() -> list[_Frame]:
    try:
        return _stack_var.get()
    except LookupError:
        stack: list[_Frame] = []
        _stack_var.set(stack)
        return stack


def _current_frame() -> _Frame | None:
    try:
        stack = _stack_var.get()
    except LookupError:
        return None
    return stack[-1] if stack else None


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return None


def _safe_repr(params: Any) -> str | None:
    if params is None:
        return None
    try:
        out = repr(params)
    except Exception:
        return "<unrepresentable>"
    if len(out) > PARAMS_REPR_LIMIT:
        return out[:PARAMS_REPR_LIMIT] + "...(truncated)"
    return out


def _truncate_sql(sql: str, limit: int | None) -> tuple[str, bool]:
    if limit is None or len(sql) <= limit:
        return sql, False
    return sql[:limit] + "...(truncated)", True


def _write_record(state: _ProfilerState, record: OpRecord) -> None:
    state.fp.write(json.dumps(record.to_dict(), default=str))
    state.fp.write("\n")


# ---------- bootstrap handling ----------


def _ensure_bootstrap_open(state: _ProfilerState) -> None:
    """First time a SQL statement fires before any op frame, start a synthetic
    ``__bootstrap__`` frame so DDL like ``CREATE TABLE django_migrations``
    (issued by ``MigrationRecorder.ensure_schema``) is still attributed."""
    if state.bootstrap_started_at:
        return
    state.bootstrap_started_at = datetime.now(UTC).isoformat()
    state.bootstrap_monotonic_start = time.monotonic()


def _finalize_bootstrap_if_needed(state: _ProfilerState) -> None:
    if state.finalized_bootstrap or not state.bootstrap_started_at:
        state.finalized_bootstrap = True
        return
    state.finalized_bootstrap = True
    duration_ms = (time.monotonic() - state.bootstrap_monotonic_start) * 1000.0
    sql_total_ms = sum(s.duration_ms for s in state.bootstrap_sql)
    record = OpRecord(
        database=state.database,
        app_label="__bootstrap__",
        migration_name="__bootstrap__",
        operation_index=-1,
        operation_type="__bootstrap__",
        describe="Pre-migration bootstrap DDL (django_migrations table, etc.)",
        started_at=state.bootstrap_started_at,
        duration_ms=duration_ms,
        sql_count=len(state.bootstrap_sql),
        sql_total_ms=sql_total_ms,
        sql_statements=state.bootstrap_sql,
    )
    _write_record(state, record)


# ---------- op patching ----------


def _iter_operation_subclasses() -> Iterator[type[Operation]]:
    """Yield every loaded concrete subclass of ``Operation``."""
    seen: set[type[Operation]] = set()

    def walk(cls: type[Operation]) -> Iterator[type[Operation]]:
        for sub in cls.__subclasses__():
            if sub in seen:
                continue
            seen.add(sub)
            yield sub
            yield from walk(sub)

    yield from walk(Operation)


def _make_op_wrapper(original_method: Any, state: _ProfilerState) -> Any:
    def wrapped(
        op_self: Operation,
        app_label: str,
        schema_editor: Any,
        from_state: Any,
        to_state: Any,
    ) -> Any:
        op_type = op_self.__class__.__name__
        try:
            target_alias = schema_editor.connection.alias
        except AttributeError:
            target_alias = state.database

        stack = _get_stack()
        parent_index = stack[-1].record.operation_index if stack else None
        op_index = state.current_op_index
        # Only advance the migration-level counter for top-level ops, not nested
        # ones inside SeparateDatabaseAndState. Those keep the parent's index
        # relationship via parent_op_index.
        if not stack:
            state.current_op_index += 1

        record = OpRecord(
            database=target_alias,
            app_label=app_label,
            migration_name=state.current_migration_name,
            operation_index=op_index,
            operation_type=op_type,
            describe=_safe_describe(op_self),
            started_at=datetime.now(UTC).isoformat(),
            is_runpython=op_type == "RunPython",
            is_state_only=op_type in STATE_ONLY_OPERATIONS,
            parent_op_index=parent_index,
            metadata=extract(op_self),
        )
        frame = _Frame(record=record, monotonic_start=time.monotonic(), target_connection_alias=target_alias)
        stack.append(frame)

        # First op fires → bootstrap window is closing.
        if not state.finalized_bootstrap:
            _finalize_bootstrap_if_needed(state)

        try:
            return original_method(op_self, app_label, schema_editor, from_state, to_state)
        except Exception as exc:
            record.error = f"{exc.__class__.__name__}: {exc}"
            raise
        finally:
            record.duration_ms = (time.monotonic() - frame.monotonic_start) * 1000.0
            record.sql_count = frame.sql_emitted
            record.sql_total_ms = sum(s.duration_ms for s in record.sql_statements)
            record.sql_truncated_count = max(0, frame.sql_emitted - len(record.sql_statements))
            stack.pop()
            _write_record(state, record)

    return wrapped


def _safe_describe(op: Operation) -> str:
    try:
        return op.describe()
    except Exception as exc:
        return f"<describe failed: {exc.__class__.__name__}>"


def _patch_migration_apply(state: _ProfilerState) -> Any:
    """Wrap ``Migration.apply`` so we know which migration's operations are
    running AND so we can record the migration's total wall-clock (which
    includes ``state_forwards``, ``project_state.clone()``, autodetector cost
    — i.e. the Python-side overhead that ``database_forwards`` timings miss)."""
    original = Migration.apply

    def wrapped(self: Migration, *args: Any, **kwargs: Any) -> Any:
        prev_name = state.current_migration_name
        prev_app = state.current_migration_app
        prev_op_index = state.current_op_index
        state.current_migration_name = self.name
        state.current_migration_app = self.app_label
        state.current_op_index = 0

        apply_started_at = datetime.now(UTC).isoformat()
        apply_t0 = time.monotonic()
        try:
            return original(self, *args, **kwargs)
        finally:
            apply_duration_ms = (time.monotonic() - apply_t0) * 1000.0
            # Emit a summary record so the analyze command can compute the
            # python-overhead portion of each migration.
            summary = {
                "_kind": "migration_summary",
                "database": state.database,
                "app_label": self.app_label,
                "migration_name": self.name,
                "started_at": apply_started_at,
                "apply_duration_ms": apply_duration_ms,
            }
            state.fp.write(json.dumps(summary) + "\n")
            state.current_migration_name = prev_name
            state.current_migration_app = prev_app
            state.current_op_index = prev_op_index

    Migration.apply = wrapped  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
    return original


def _patch_operations(state: _ProfilerState) -> list[tuple[type[Operation], Any]]:
    patched: list[tuple[type[Operation], Any]] = []
    for cls in _iter_operation_subclasses():
        original = cls.__dict__.get("database_forwards")
        if original is None:
            # Subclass inherits database_forwards from its parent; we'd patch
            # the parent separately. Skip to avoid double-patching.
            continue
        wrapper = _make_op_wrapper(original, state)
        cls.database_forwards = wrapper
        patched.append((cls, original))
    return patched


# ---------- SQL patching ----------


def _make_schema_editor_wrapper(original_execute: Any, state: _ProfilerState) -> Any:
    def wrapped(self: BaseDatabaseSchemaEditor, sql: Any, params: Any = ()) -> Any:
        frame = _current_frame()
        sql_str = str(sql) if sql is not None else ""

        if frame is None:
            # Bootstrap DDL — attribute to a synthetic record flushed on first op.
            _ensure_bootstrap_open(state)
            t0 = time.monotonic()
            try:
                return original_execute(self, sql, params)
            finally:
                truncated_sql, was_truncated = _truncate_sql(sql_str, state.truncation_limit)
                duration_ms = (time.monotonic() - t0) * 1000.0
                ts_offset_ms = (time.monotonic() - state.bootstrap_monotonic_start) * 1000.0
                if len(state.bootstrap_sql) < MAX_SQL_PER_OP:
                    state.bootstrap_sql.append(
                        SqlRecord(
                            sql=truncated_sql,
                            sql_truncated=was_truncated,
                            params_repr=_safe_repr(params),
                            duration_ms=duration_ms,
                            source="schema_editor",
                            ts_offset_ms=ts_offset_ms,
                        )
                    )
            return None

        frame.in_schema_editor_call = True
        t0 = time.monotonic()
        try:
            return original_execute(self, sql, params)
        finally:
            duration_ms = (time.monotonic() - t0) * 1000.0
            ts_offset_ms = (time.monotonic() - frame.monotonic_start) * 1000.0
            frame.in_schema_editor_call = False
            frame.sql_emitted += 1
            if len(frame.record.sql_statements) < MAX_SQL_PER_OP:
                truncated_sql, was_truncated = _truncate_sql(sql_str, state.truncation_limit)
                frame.record.sql_statements.append(
                    SqlRecord(
                        sql=truncated_sql,
                        sql_truncated=was_truncated,
                        params_repr=_safe_repr(params),
                        duration_ms=duration_ms,
                        source="schema_editor",
                        ts_offset_ms=ts_offset_ms,
                    )
                )

    return wrapped


def _make_cursor_wrapper(state: _ProfilerState) -> Any:
    def cursor_wrapper(execute: Any, sql: Any, params: Any, many: bool, context: dict[str, Any]) -> Any:
        frame = _current_frame()
        if frame is None or frame.in_schema_editor_call:
            return execute(sql, params, many, context)

        t0 = time.monotonic()
        try:
            return execute(sql, params, many, context)
        finally:
            duration_ms = (time.monotonic() - t0) * 1000.0
            ts_offset_ms = (time.monotonic() - frame.monotonic_start) * 1000.0
            frame.sql_emitted += 1
            if len(frame.record.sql_statements) < MAX_SQL_PER_OP:
                sql_str = str(sql) if sql is not None else ""
                truncated_sql, was_truncated = _truncate_sql(sql_str, state.truncation_limit)
                frame.record.sql_statements.append(
                    SqlRecord(
                        sql=truncated_sql,
                        sql_truncated=was_truncated,
                        params_repr=_safe_repr(params),
                        duration_ms=duration_ms,
                        source="cursor",
                        ts_offset_ms=ts_offset_ms,
                    )
                )

    return cursor_wrapper


# ---------- the contextmanager ----------


@contextmanager
def profile_migrations(
    *,
    database: str,
    output_path: Path,
    full_sql: bool = False,
) -> Iterator[Path]:
    """Profile a single ``migrate`` invocation.

    Writes one JSONL file at ``output_path``. The first line is a ``_meta``
    header; every subsequent line is an ``OpRecord.to_dict()``. Restores all
    patches in ``finally``.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    truncation_limit = None if full_sql else SQL_TRUNCATION_LIMIT
    fp = output_path.open("w", buffering=1, encoding="utf-8")

    state = _ProfilerState(fp=fp, database=database, truncation_limit=truncation_limit)
    state_token = _state_var.set(state)
    stack_token = _stack_var.set([])

    # Header line.
    meta = {
        "_meta": {
            "schema_version": SCHEMA_VERSION,
            "database": database,
            "django_version": django.get_version(),
            "python_version": sys.version.split()[0],
            "git_sha": _git_sha(),
            "hostname": socket.gethostname(),
            "started_at": datetime.now(UTC).isoformat(),
            "full_sql": full_sql,
            "sql_truncation_limit": truncation_limit,
        }
    }
    fp.write(json.dumps(meta) + "\n")

    # Force migration loader to import every migration module so all
    # Operation subclasses are loaded before we patch.
    _prime_operation_subclasses(database)

    migration_apply_original = _patch_migration_apply(state)
    patched_ops = _patch_operations(state)

    schema_editor_original = BaseDatabaseSchemaEditor.execute
    BaseDatabaseSchemaEditor.execute = _make_schema_editor_wrapper(schema_editor_original, state)  # type: ignore[method-assign]

    cursor_wrapper = _make_cursor_wrapper(state)
    installed_on: list[str] = []
    for alias in settings.DATABASES:
        try:
            connections[alias].execute_wrappers.append(cursor_wrapper)
            installed_on.append(alias)
        except Exception:
            # Best-effort: an alias that fails to open shouldn't break profiling
            # of the rest.
            pass

    try:
        yield output_path
    finally:
        for alias in installed_on:
            try:
                connections[alias].execute_wrappers.remove(cursor_wrapper)
            except (ValueError, Exception):
                pass

        BaseDatabaseSchemaEditor.execute = schema_editor_original  # type: ignore[method-assign]

        for cls, original in patched_ops:
            cls.database_forwards = original

        Migration.apply = migration_apply_original  # type: ignore[method-assign]

        _finalize_bootstrap_if_needed(state)

        _stack_var.reset(stack_token)
        _state_var.reset(state_token)

        fp.close()


def _prime_operation_subclasses(database: str) -> None:
    """Trigger the migration loader so every concrete ``Operation`` subclass
    in every app is imported before we patch ``database_forwards``."""
    try:
        from django.db.migrations.loader import MigrationLoader

        MigrationLoader(connections[database], ignore_no_migrations=True)
    except Exception:
        # If we can't load the graph, fall back to whatever subclasses are
        # currently loaded — patching is still useful, just less complete.
        pass
