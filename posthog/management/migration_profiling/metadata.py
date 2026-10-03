"""Per-operation metadata extractors for the profiler.

Each Django migration operation subclass exposes different attributes — we
pull out the ones useful for grouping in the report (model name, field name,
index name, RunSQL preview, RunPython callable). Keyed by class name to
avoid hard-importing every Django operation module at import time.

Anything not in EXTRACTORS still gets an OpRecord; the metadata dict will
just be empty and the analyze command falls back to ``describe``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Limit on inline RunSQL snippets in the metadata dict. Full SQL still lands
# in sql_statements when it executes against the DB.
_RUN_SQL_PREVIEW_CHARS = 200


def _create_model(op: Any) -> dict[str, Any]:
    return {"model_name": op.name}


def _delete_model(op: Any) -> dict[str, Any]:
    return {"model_name": op.name}


def _rename_model(op: Any) -> dict[str, Any]:
    return {"model_name": op.old_name, "new_name": op.new_name}


def _alter_model_table(op: Any) -> dict[str, Any]:
    return {"model_name": op.name, "table": op.table}


def _add_field(op: Any) -> dict[str, Any]:
    return {"model_name": op.model_name, "field_name": op.name}


def _remove_field(op: Any) -> dict[str, Any]:
    return {"model_name": op.model_name, "field_name": op.name}


def _alter_field(op: Any) -> dict[str, Any]:
    return {"model_name": op.model_name, "field_name": op.name}


def _rename_field(op: Any) -> dict[str, Any]:
    return {
        "model_name": op.model_name,
        "old_name": op.old_name,
        "new_name": op.new_name,
    }


def _add_index(op: Any) -> dict[str, Any]:
    return {"model_name": op.model_name, "index_name": getattr(op.index, "name", None)}


def _remove_index(op: Any) -> dict[str, Any]:
    return {"model_name": op.model_name, "index_name": op.name}


def _rename_index(op: Any) -> dict[str, Any]:
    return {
        "model_name": op.model_name,
        "old_name": op.old_name,
        "new_name": op.new_name,
    }


def _add_constraint(op: Any) -> dict[str, Any]:
    return {
        "model_name": op.model_name,
        "constraint_name": getattr(op.constraint, "name", None),
    }


def _remove_constraint(op: Any) -> dict[str, Any]:
    return {"model_name": op.model_name, "constraint_name": op.name}


def _alter_unique_together(op: Any) -> dict[str, Any]:
    return {"model_name": op.name}


def _alter_index_together(op: Any) -> dict[str, Any]:
    return {"model_name": op.name}


def _alter_model_options(op: Any) -> dict[str, Any]:
    return {"model_name": op.name}


def _alter_model_managers(op: Any) -> dict[str, Any]:
    return {"model_name": op.name}


def _run_sql(op: Any) -> dict[str, Any]:
    raw = op.sql
    if isinstance(raw, list):
        preview = "; ".join(str(item)[:_RUN_SQL_PREVIEW_CHARS] for item in raw[:3])
    else:
        preview = str(raw)[:_RUN_SQL_PREVIEW_CHARS] if raw else None
    return {"sql_preview": preview}


def _run_python(op: Any) -> dict[str, Any]:
    callable_obj = op.code
    return {
        "is_runpython": True,
        "callable": getattr(callable_obj, "__qualname__", repr(callable_obj)),
    }


def _separate_db_and_state(op: Any) -> dict[str, Any]:
    return {
        "wraps_database_ops": [c.__class__.__name__ for c in (op.database_operations or [])],
        "wraps_state_ops": [c.__class__.__name__ for c in (op.state_operations or [])],
    }


EXTRACTORS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "CreateModel": _create_model,
    "DeleteModel": _delete_model,
    "RenameModel": _rename_model,
    "AlterModelTable": _alter_model_table,
    "AddField": _add_field,
    "RemoveField": _remove_field,
    "AlterField": _alter_field,
    "RenameField": _rename_field,
    "AddIndex": _add_index,
    "AddIndexConcurrently": _add_index,
    "RemoveIndex": _remove_index,
    "RemoveIndexConcurrently": _remove_index,
    "RenameIndex": _rename_index,
    "AddConstraint": _add_constraint,
    "RemoveConstraint": _remove_constraint,
    "AlterUniqueTogether": _alter_unique_together,
    "AlterIndexTogether": _alter_index_together,
    "AlterModelOptions": _alter_model_options,
    "AlterModelManagers": _alter_model_managers,
    "RunSQL": _run_sql,
    "RunPython": _run_python,
    "SeparateDatabaseAndState": _separate_db_and_state,
}


# Operations whose database_forwards is a no-op (state-only). Recorded with
# is_state_only=True so the analyze command can filter them out of totals.
STATE_ONLY_OPERATIONS: frozenset[str] = frozenset(
    {
        "AlterModelOptions",
        "AlterModelManagers",
        "AlterOrderWithRespectTo",
    }
)


def extract(op: Any) -> dict[str, Any]:
    """Return the structured metadata dict for ``op``, or ``{}`` if no extractor."""
    extractor = EXTRACTORS.get(op.__class__.__name__)
    if extractor is None:
        return {}
    try:
        return extractor(op)
    except Exception as exc:
        return {"_extract_error": f"{exc.__class__.__name__}: {exc}"}
