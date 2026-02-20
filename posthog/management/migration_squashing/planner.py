from __future__ import annotations

import re
import json
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from django.apps import apps
from django.db import migrations
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.optimizer import MigrationOptimizer
from django.db.migrations.writer import MigrationWriter

from posthog.management.migration_squashing.policy import BootstrapPolicy

_MIGRATION_PREFIX_RE = re.compile(r"^(?P<prefix>\d+)_")
_SQUASH_SUFFIX_RE = re.compile(r"[^a-zA-Z0-9_]+")
_SQL_COMMENT_RE = re.compile(r"--.*?$", re.MULTILINE)
_MIGRATION_MODULE_CALLABLE_RE = re.compile(r"\.migrations\.\d+_")
_SQL_CONCURRENTLY_RE = re.compile(r"\bCONCURRENTLY\b", re.IGNORECASE)
_SQL_DROP_TABLE_IF_EXISTS_RE = re.compile(r"^DROP TABLE IF EXISTS (?P<table>[A-Za-z_][A-Za-z0-9_\.]*)$", re.IGNORECASE)
_SQL_DROP_TABLE_RE = re.compile(
    r"^DROP TABLE(?: IF EXISTS)? (?P<table>[A-Za-z_][A-Za-z0-9_\.]*)$",
    re.IGNORECASE,
)
_SQL_CREATE_TABLE_RE = re.compile(
    r"^CREATE TABLE(?: IF NOT EXISTS)? (?P<table>[A-Za-z_][A-Za-z0-9_\.]*)\b",
    re.IGNORECASE,
)
_SQL_ALTER_TABLE_RE = re.compile(
    r"^ALTER TABLE(?: ONLY)? (?P<table>[A-Za-z_][A-Za-z0-9_\.]*)\b",
    re.IGNORECASE,
)
_SQL_DROP_INDEX_IF_EXISTS_RE = re.compile(
    r"^DROP INDEX(?: CONCURRENTLY)? IF EXISTS (?P<index>[A-Za-z_][A-Za-z0-9_]*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OperationBlocker:
    migration: str
    operation_index: int
    operation_type: str
    reason: str
    nested_path: str | None = None
    fingerprint: str | None = None


@dataclass
class SquashAnalysis:
    app_label: str
    requested_start: str
    requested_end: str
    requested_span: list[str]
    included_span: list[str]
    blockers: list[OperationBlocker]
    dependencies: list[tuple[str, str]]
    replaces: list[tuple[str, str]]
    generated_migration_name: str
    original_operation_count: int
    optimized_operation_count: int
    requires_non_atomic: bool
    state_equivalent: bool
    state_differences: list[str] = field(default_factory=list)
    optimized_operations: list[Any] = field(default_factory=list, repr=False)

    @property
    def included_start(self) -> str | None:
        return self.included_span[0] if self.included_span else None

    @property
    def included_end(self) -> str | None:
        return self.included_span[-1] if self.included_span else None

    @property
    def excluded_span(self) -> list[str]:
        return [name for name in self.requested_span if name not in set(self.included_span)]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "app_label": self.app_label,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "requested_span": self.requested_span,
            "included_span": self.included_span,
            "excluded_span": self.excluded_span,
            "dependencies": self.dependencies,
            "replaces": self.replaces,
            "generated_migration_name": self.generated_migration_name,
            "original_operation_count": self.original_operation_count,
            "optimized_operation_count": self.optimized_operation_count,
            "requires_non_atomic": self.requires_non_atomic,
            "state_equivalent": self.state_equivalent,
            "state_differences": self.state_differences,
            "blockers": [asdict(blocker) for blocker in self.blockers],
        }


class MigrationSquashPlanner:
    """Plans deterministic, state-safe migration squashes for one Django app."""

    SAFE_OPERATION_TYPES = frozenset(
        {
            "CreateModel",
            "DeleteModel",
            "RenameModel",
            "AlterModelTable",
            "AlterModelTableComment",
            "AlterModelOptions",
            "AlterModelManagers",
            "AlterOrderWithRespectTo",
            "AddField",
            "RemoveField",
            "AlterField",
            "RenameField",
            "AddIndex",
            "RemoveIndex",
            "RenameIndex",
            "AddConstraint",
            "RemoveConstraint",
            "AlterUniqueTogether",
            "AlterIndexTogether",
            "AddIndexConcurrently",
            "RemoveIndexConcurrently",
            "AddConstraintNotValid",
            "ValidateConstraint",
        }
    )
    SAFE_MODULE_PREFIXES = (
        "django.db.migrations.operations",
        "django.contrib.postgres.operations",
    )
    OPAQUE_OPERATION_TYPES = frozenset({"RunPython", "RunSQL"})
    RUNSQL_DML_KEYWORDS = (" UPDATE ", " DELETE ", " INSERT ", " TRUNCATE ")

    def __init__(
        self,
        loader: MigrationLoader,
        app_label: str,
        allow_operation_types: set[str] | None = None,
        bootstrap_policy: BootstrapPolicy | None = None,
    ) -> None:
        self.loader = loader
        self.app_label = app_label
        self.allow_operation_types = allow_operation_types or set()
        self.bootstrap_policy = bootstrap_policy or BootstrapPolicy()

    def infer_default_end(self) -> str:
        max_file_name = self._read_max_migration_file()
        if max_file_name and (self.app_label, max_file_name) in self.loader.disk_migrations:
            return max_file_name

        app_names = [
            name
            for (app, name), migration in self.loader.disk_migrations.items()
            if app == self.app_label and not getattr(migration, "replaces", None)
        ]
        if not app_names:
            raise ValueError(f"No migrations found for app '{self.app_label}'.")
        return sorted(app_names, key=self._migration_sort_key)[-1]

    def infer_default_start(self) -> str:
        app_names = [
            name
            for (app, name), migration in self.loader.disk_migrations.items()
            if app == self.app_label and not getattr(migration, "replaces", None)
        ]
        if not app_names:
            raise ValueError(f"No migrations found for app '{self.app_label}'.")

        latest_replaced = self._latest_replaced_migration()
        if latest_replaced is None:
            return sorted(app_names, key=self._migration_sort_key)[0]

        candidates = [
            name for name in app_names if self._migration_sort_key(name) > self._migration_sort_key(latest_replaced)
        ]
        if not candidates:
            raise ValueError(
                f"Could not infer a start migration after squashed migration '{latest_replaced}' for app '{self.app_label}'."
            )
        return sorted(candidates, key=self._migration_sort_key)[0]

    def analyze_span(self, start_name: str, end_name: str, name_suffix: str | None = None) -> SquashAnalysis:
        requested_span = self._requested_span(start_name, end_name)
        blockers: list[OperationBlocker] = []
        included_span: list[str] = []

        for migration_name in requested_span:
            migration = self.loader.disk_migrations[(self.app_label, migration_name)]
            migration_blockers = self._find_blockers_for_migration(migration_name, migration)
            if migration_blockers:
                blockers.extend(migration_blockers)
                break
            included_span.append(migration_name)

        if not included_span:
            return SquashAnalysis(
                app_label=self.app_label,
                requested_start=start_name,
                requested_end=end_name,
                requested_span=requested_span,
                included_span=[],
                blockers=blockers,
                dependencies=[],
                replaces=[],
                generated_migration_name=self.build_squashed_name(start_name, start_name, name_suffix),
                original_operation_count=0,
                optimized_operation_count=0,
                requires_non_atomic=False,
                state_equivalent=False,
                state_differences=["No squashable migrations in the requested span."],
                optimized_operations=[],
            )

        included_keys = [(self.app_label, name) for name in included_span]
        original_operations = self._flatten_operations(included_keys)
        optimized_operations = MigrationOptimizer().optimize(original_operations, self.app_label)

        dependencies = self._collect_dependencies(included_keys)
        replaces = [(self.app_label, name) for name in included_span]
        generated_migration_name = self.build_squashed_name(included_span[0], included_span[-1], name_suffix)
        requires_non_atomic = self._requires_non_atomic(optimized_operations)

        state_equivalent, state_differences = self._verify_state_equivalence(included_keys, optimized_operations)

        return SquashAnalysis(
            app_label=self.app_label,
            requested_start=start_name,
            requested_end=end_name,
            requested_span=requested_span,
            included_span=included_span,
            blockers=blockers,
            dependencies=dependencies,
            replaces=replaces,
            generated_migration_name=generated_migration_name,
            original_operation_count=len(original_operations),
            optimized_operation_count=len(optimized_operations),
            requires_non_atomic=requires_non_atomic,
            state_equivalent=state_equivalent,
            state_differences=state_differences,
            optimized_operations=optimized_operations,
        )

    def build_squashed_name(self, start_name: str, end_name: str, name_suffix: str | None = None) -> str:
        start_prefix = self._migration_prefix(start_name)
        end_prefix = self._migration_prefix(end_name)
        if name_suffix:
            suffix = self._normalize_suffix(name_suffix)
        else:
            suffix = self._normalize_suffix(end_name.split("_", 1)[-1] if "_" in end_name else end_name)
        return f"{start_prefix}_squashed_{end_prefix}_{suffix}"

    def write_migration(
        self,
        analysis: SquashAnalysis,
        rewrite_concurrent_indexes: bool = False,
        overwrite_existing: bool = False,
    ) -> Path:
        if not analysis.included_span:
            raise ValueError("Cannot write a squash migration with an empty included span.")
        if not analysis.state_equivalent:
            raise ValueError("Cannot write a squash migration when state equivalence check failed.")

        operations_for_write = self._prepare_operations_for_write(
            analysis.optimized_operations,
            rewrite_concurrent_indexes=rewrite_concurrent_indexes,
        )
        included_keys = [(self.app_label, name) for name in analysis.included_span]
        write_state_equivalent, write_state_differences = self._verify_state_equivalence(
            included_keys, operations_for_write
        )
        if not write_state_equivalent:
            summary = "; ".join(write_state_differences[:3])
            raise ValueError(f"Cannot write migration after rewrite transforms: {summary}")
        operations_require_non_atomic = any(
            self._operation_requires_non_atomic(operation) for operation in operations_for_write
        )
        requires_non_atomic = operations_require_non_atomic

        migration = migrations.Migration(analysis.generated_migration_name, self.app_label)
        migration.dependencies = analysis.dependencies
        migration.operations = operations_for_write
        migration.replaces = analysis.replaces
        if requires_non_atomic:
            migration.atomic = False

        writer = MigrationWriter(migration)
        path = Path(writer.path)
        rendered_migration = writer.as_string()
        if requires_non_atomic:
            rendered_migration = self._inject_non_atomic_flag(rendered_migration)
        if path.exists():
            existing_migration = path.read_text()
            if existing_migration == rendered_migration:
                return path
            if not overwrite_existing:
                raise ValueError(f"Migration file already exists with different content: {path}")
        path.write_text(rendered_migration)
        return path

    def _prepare_operations_for_write(self, operations: list[Any], rewrite_concurrent_indexes: bool) -> list[Any]:
        prepared_operations = operations
        if rewrite_concurrent_indexes:
            prepared_operations = [self._rewrite_operation_for_bootstrap(operation) for operation in operations]
        prepared_operations = [self._normalize_custom_write_operations(operation) for operation in prepared_operations]
        prepared_operations = self._fold_create_model_index_renames(prepared_operations)
        prepared_operations = self._fold_create_model_fk_to_plain_field_alters(prepared_operations)
        prepared_operations = self._fold_create_model_fk_index_drops(prepared_operations)
        return self._fold_ephemeral_create_model_lifecycle(prepared_operations)

    def _normalize_custom_write_operations(self, operation: Any) -> Any:
        if isinstance(operation, migrations.SeparateDatabaseAndState):
            return migrations.SeparateDatabaseAndState(
                database_operations=[
                    self._normalize_custom_write_operations(nested)
                    for nested in getattr(operation, "database_operations", [])
                ],
                state_operations=[
                    self._normalize_custom_write_operations(nested)
                    for nested in getattr(operation, "state_operations", [])
                ],
            )
        if isinstance(operation, migrations.AlterField) and operation.__class__ is not migrations.AlterField:
            return migrations.AlterField(
                model_name=operation.model_name,
                name=operation.name,
                field=operation.field,
                preserve_default=getattr(operation, "preserve_default", True),
            )
        return operation

    def _rewrite_operation_for_policy(
        self,
        migration_name: str,
        operation_index: int,
        operation: Any,
        nested_path: tuple[tuple[str, int], ...] = (),
    ) -> Any:
        op_type = operation.__class__.__name__
        nested_path_str = self._format_nested_path(nested_path)
        fingerprint = self._operation_fingerprint(operation)

        if op_type == "SeparateDatabaseAndState":
            resolution = self.bootstrap_policy.resolve(
                app_label=self.app_label,
                migration=migration_name,
                operation_index=operation_index,
                nested_path=nested_path_str,
                fingerprint=fingerprint,
            )
            if resolution and resolution.action == "noop":
                raise ValueError(
                    "Bootstrap policy action 'noop' is not supported for SeparateDatabaseAndState "
                    f"({self.app_label}.{migration_name} op#{operation_index}, nested_path={nested_path_str!r}). "
                    "Mark nested RunSQL/RunPython operations as noop instead."
                )
            if resolution and resolution.action == "keep":
                return operation

            database_operations = [
                self._rewrite_operation_for_policy(
                    migration_name=migration_name,
                    operation_index=operation_index,
                    operation=nested_op,
                    nested_path=(*nested_path, ("database_operations", idx)),
                )
                for idx, nested_op in enumerate(getattr(operation, "database_operations", []))
            ]
            state_operations = [
                self._rewrite_operation_for_policy(
                    migration_name=migration_name,
                    operation_index=operation_index,
                    operation=nested_op,
                    nested_path=(*nested_path, ("state_operations", idx)),
                )
                for idx, nested_op in enumerate(getattr(operation, "state_operations", []))
            ]
            return migrations.SeparateDatabaseAndState(
                database_operations=database_operations,
                state_operations=state_operations,
            )

        resolution = self.bootstrap_policy.resolve(
            app_label=self.app_label,
            migration=migration_name,
            operation_index=operation_index,
            nested_path=nested_path_str,
            fingerprint=fingerprint,
        )
        if resolution is None:
            return operation
        if resolution.action == "keep":
            return operation
        if resolution.action == "noop_if_empty":
            if not resolution.tables:
                raise ValueError(
                    "Bootstrap policy action 'noop_if_empty' requires non-empty table probes for "
                    f"{self.app_label}.{migration_name} op#{operation_index} nested_path={nested_path_str!r}."
                )
            return self._noop_if_empty_operation(
                operation=operation,
                migration_name=migration_name,
                operation_index=operation_index,
                nested_path=nested_path_str,
                tables=list(resolution.tables),
            )
        if resolution.action != "noop":
            raise ValueError(
                f"Unsupported bootstrap policy action '{resolution.action}' for "
                f"{self.app_label}.{migration_name} op#{operation_index} nested_path={nested_path_str!r}."
            )
        return self._noop_operation(
            operation=operation,
            migration_name=migration_name,
            operation_index=operation_index,
            nested_path=nested_path_str,
        )

    def _noop_operation(
        self,
        operation: Any,
        migration_name: str,
        operation_index: int,
        nested_path: str | None,
    ) -> Any:
        op_type = operation.__class__.__name__
        if op_type == "RunPython":
            return migrations.RunPython(
                code=migrations.RunPython.noop,
                reverse_code=migrations.RunPython.noop,
                atomic=getattr(operation, "atomic", None),
                hints=getattr(operation, "hints", None),
                elidable=getattr(operation, "elidable", False),
            )
        if op_type == "RunSQL":
            return migrations.RunSQL(
                sql=migrations.RunSQL.noop,
                reverse_sql=migrations.RunSQL.noop,
                state_operations=getattr(operation, "state_operations", None),
                hints=getattr(operation, "hints", None),
                elidable=getattr(operation, "elidable", False),
            )
        raise ValueError(
            "Bootstrap policy action 'noop' is only supported for RunPython/RunSQL operations. "
            f"Got {op_type} at {self.app_label}.{migration_name} op#{operation_index} nested_path={nested_path!r}."
        )

    def _noop_if_empty_operation(
        self,
        operation: Any,
        migration_name: str,
        operation_index: int,
        nested_path: str | None,
        tables: list[str],
    ) -> Any:
        op_type = operation.__class__.__name__
        guard_sql = self._build_noop_if_empty_guard_sql(
            migration_name=migration_name,
            operation_index=operation_index,
            nested_path=nested_path,
            tables=tables,
        )
        if op_type == "RunPython":
            return migrations.RunSQL(
                sql=guard_sql,
                reverse_sql=migrations.RunSQL.noop,
                hints=getattr(operation, "hints", None),
                elidable=getattr(operation, "elidable", False),
            )
        if op_type == "RunSQL":
            return migrations.RunSQL(
                sql=guard_sql,
                reverse_sql=migrations.RunSQL.noop,
                state_operations=getattr(operation, "state_operations", None),
                hints=getattr(operation, "hints", None),
                elidable=getattr(operation, "elidable", False),
            )
        raise ValueError(
            "Bootstrap policy action 'noop_if_empty' is only supported for RunPython/RunSQL operations. "
            f"Got {op_type} at {self.app_label}.{migration_name} op#{operation_index} nested_path={nested_path!r}."
        )

    def _build_noop_if_empty_guard_sql(
        self,
        migration_name: str,
        operation_index: int,
        nested_path: str | None,
        tables: list[str],
    ) -> str:
        if not tables:
            raise ValueError("Bootstrap policy action 'noop_if_empty' requires at least one table probe.")
        context = f"{self.app_label}.{migration_name} op#{operation_index}"
        if nested_path:
            context += f" path={nested_path}"
        context_literal = self._sql_string_literal(context)
        table_literals = ", ".join(self._sql_string_literal(table) for table in tables)
        return (
            "DO $$\n"
            "DECLARE\n"
            "    _table text;\n"
            "    _resolved regclass;\n"
            "    _has_rows boolean;\n"
            "BEGIN\n"
            f"    FOREACH _table IN ARRAY ARRAY[{table_literals}] LOOP\n"
            "        _resolved := to_regclass(_table);\n"
            "        IF _resolved IS NULL THEN\n"
            "            RAISE EXCEPTION 'Bootstrap policy noop_if_empty table % does not exist for %', "
            f"_table, {context_literal};\n"
            "        END IF;\n"
            "        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s LIMIT 1)', _resolved) INTO _has_rows;\n"
            "        IF _has_rows THEN\n"
            "            RAISE EXCEPTION 'Bootstrap policy noop_if_empty blocked: table % is not empty for %', "
            f"_table, {context_literal};\n"
            "        END IF;\n"
            "    END LOOP;\n"
            "END\n"
            "$$;"
        )

    @staticmethod
    def _sql_string_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _fold_create_model_index_renames(self, operations: list[Any]) -> list[Any]:
        prepared_operations: list[Any] = []
        create_model_by_name: dict[str, Any] = {}

        for operation in operations:
            op_type = operation.__class__.__name__

            if op_type == "CreateModel":
                create_model_by_name[operation.name.lower()] = operation
                prepared_operations.append(operation)
                continue

            if op_type == "RenameModel":
                old_name = operation.old_name.lower()
                new_name = operation.new_name.lower()
                if old_name in create_model_by_name:
                    create_model_by_name[new_name] = create_model_by_name.pop(old_name)
                prepared_operations.append(operation)
                continue

            if op_type == "DeleteModel":
                create_model_by_name.pop(operation.name.lower(), None)
                prepared_operations.append(operation)
                continue

            if op_type == "RenameIndex":
                model_name = getattr(operation, "model_name", "").lower()
                create_model_operation = create_model_by_name.get(model_name)
                if create_model_operation and self._rename_index_in_create_model(
                    create_model_operation=create_model_operation,
                    old_name=operation.old_name,
                    new_name=operation.new_name,
                ):
                    continue

            prepared_operations.append(operation)

        return prepared_operations

    def _fold_create_model_fk_to_plain_field_alters(self, operations: list[Any]) -> list[Any]:
        prepared_operations: list[Any] = []
        create_model_by_name: dict[str, int] = {}

        for operation in operations:
            op_type = operation.__class__.__name__

            if op_type == "CreateModel":
                create_model_by_name[operation.name.lower()] = len(prepared_operations)
                prepared_operations.append(operation)
                continue

            if op_type == "RenameModel":
                old_name = operation.old_name.lower()
                new_name = operation.new_name.lower()
                if old_name in create_model_by_name:
                    create_model_by_name[new_name] = create_model_by_name.pop(old_name)
                prepared_operations.append(operation)
                continue

            if op_type == "DeleteModel":
                create_model_by_name.pop(operation.name.lower(), None)
                prepared_operations.append(operation)
                continue

            if op_type == "AlterField":
                model_name = str(getattr(operation, "model_name", "")).lower()
                create_model_idx = create_model_by_name.get(model_name)
                if create_model_idx is None:
                    prepared_operations.append(operation)
                    continue

                create_model_operation = prepared_operations[create_model_idx]
                if self._replace_create_model_field_for_fk_drop(
                    create_model_operation=create_model_operation,
                    field_name=str(getattr(operation, "name", "")),
                    replacement_field=getattr(operation, "field", None),
                ):
                    continue

            prepared_operations.append(operation)

        return prepared_operations

    def _replace_create_model_field_for_fk_drop(
        self,
        create_model_operation: Any,
        field_name: str,
        replacement_field: Any,
    ) -> bool:
        fields = list(getattr(create_model_operation, "fields", []))
        for idx, (existing_field_name, existing_field) in enumerate(fields):
            if str(existing_field_name) != field_name:
                continue
            if getattr(existing_field, "remote_field", None) is None:
                return False
            if getattr(replacement_field, "remote_field", None) is not None:
                return False
            fields[idx] = (existing_field_name, replacement_field)
            create_model_operation.fields = fields
            return True
        return False

    def _fold_create_model_fk_index_drops(self, operations: list[Any]) -> list[Any]:
        create_models_by_table: dict[str, Any] = {}
        removable_indices: set[int] = set()

        for idx, operation in enumerate(operations):
            op_type = operation.__class__.__name__
            if op_type == "CreateModel":
                create_models_by_table[self._model_db_table_name(operation)] = operation
                continue
            if op_type == "DeleteModel":
                model_name = getattr(operation, "name", "")
                create_model_operation = create_models_by_table.pop(
                    self._normalize_db_table_name(f"{self.app_label}_{str(model_name).lower()}"),
                    None,
                )
                if create_model_operation is not None:
                    continue
            if op_type == "RunSQL":
                drop_index_name = self._runsql_drop_index_if_exists_target(operation)
                if not drop_index_name:
                    continue
                matched = False
                for table_name, create_model_operation in create_models_by_table.items():
                    fk_field_name = self._fk_field_name_from_auto_index(
                        index_name=drop_index_name,
                        table_name=table_name,
                    )
                    if not fk_field_name:
                        continue
                    if self._set_create_model_field_db_index_false(create_model_operation, fk_field_name):
                        removable_indices.add(idx)
                        matched = True
                        break
                if matched:
                    continue

        if not removable_indices:
            return operations

        return [operation for idx, operation in enumerate(operations) if idx not in removable_indices]

    def _fold_ephemeral_create_model_lifecycle(self, operations: list[Any]) -> list[Any]:
        create_models: dict[str, tuple[int, str]] = {}
        for idx, operation in enumerate(operations):
            if operation.__class__.__name__ != "CreateModel":
                continue
            model_name = getattr(operation, "name", "")
            if not model_name:
                continue
            db_table = self._model_db_table_name(operation)
            create_models[model_name.lower()] = (idx, db_table)

        drop_tables: dict[int, str] = {}
        for idx, operation in enumerate(operations):
            drop_table = self._runsql_drop_table_if_exists_target(operation)
            if drop_table is not None:
                drop_tables[idx] = drop_table

        removable_indices: set[int] = set()
        lifecycle_candidates: list[tuple[str, str, int, int, int]] = []
        for idx, operation in enumerate(operations):
            deleted_model_name = self._state_deleted_model_name(operation)
            if not deleted_model_name:
                continue

            normalized_model_name = deleted_model_name.lower()
            create_info = create_models.get(normalized_model_name)
            if create_info is None:
                continue

            create_idx, create_table = create_info
            if create_idx >= idx:
                continue

            matching_drop_idx = None
            for drop_idx, drop_table in drop_tables.items():
                if drop_idx <= idx:
                    continue
                if drop_table == create_table:
                    matching_drop_idx = drop_idx
                    break

            if matching_drop_idx is None:
                continue

            lifecycle_candidates.append((normalized_model_name, create_table, create_idx, idx, matching_drop_idx))

        for model_name, table_name, create_idx, delete_idx, drop_idx in lifecycle_candidates:
            removable_indices.update({create_idx, delete_idx, drop_idx})
            for operation_idx in range(create_idx + 1, drop_idx):
                operation = operations[operation_idx]
                if self._operation_targets_model_or_table_exclusively(
                    operation=operation,
                    model_name=model_name,
                    table_name=table_name,
                ):
                    removable_indices.add(operation_idx)

        if not removable_indices:
            return operations

        return [operation for idx, operation in enumerate(operations) if idx not in removable_indices]

    def _state_deleted_model_name(self, operation: Any) -> str | None:
        if operation.__class__.__name__ != "SeparateDatabaseAndState":
            return None

        state_operations = getattr(operation, "state_operations", [])
        if len(state_operations) != 1:
            return None

        state_operation = state_operations[0]
        if state_operation.__class__.__name__ != "DeleteModel":
            return None

        model_name = getattr(state_operation, "name", None)
        return str(model_name) if model_name else None

    def _operation_targets_model_or_table_exclusively(self, operation: Any, model_name: str, table_name: str) -> bool:
        op_type = operation.__class__.__name__
        model_operation_types = {
            "AddField",
            "RemoveField",
            "AlterField",
            "RenameField",
            "AddConstraint",
            "RemoveConstraint",
            "AddConstraintNotValid",
            "ValidateConstraint",
            "AddIndex",
            "RemoveIndex",
            "RenameIndex",
        }

        if op_type in {"CreateModel", "DeleteModel"}:
            operation_model_name = str(getattr(operation, "name", "")).lower()
            return operation_model_name == model_name

        if op_type in model_operation_types:
            operation_model_name = str(getattr(operation, "model_name", "")).lower()
            return operation_model_name == model_name

        if op_type == "SeparateDatabaseAndState":
            nested_operations = list(getattr(operation, "database_operations", [])) + list(
                getattr(operation, "state_operations", [])
            )
            if not nested_operations:
                return False
            return all(
                self._operation_targets_model_or_table_exclusively(
                    operation=nested_operation,
                    model_name=model_name,
                    table_name=table_name,
                )
                for nested_operation in nested_operations
            )

        if op_type == "RunSQL":
            return self._runsql_targets_only_table(operation=operation, table_name=table_name)

        return False

    def _runsql_targets_only_table(self, operation: Any, table_name: str) -> bool:
        sql_statements = list(self._iter_sql_statements(getattr(operation, "sql", None)))
        if not sql_statements:
            return False
        if any(self._sql_statement_target_table(statement) != table_name for statement in sql_statements):
            return False

        reverse_sql_statements = list(self._iter_sql_statements(getattr(operation, "reverse_sql", None)))
        if reverse_sql_statements and any(
            self._sql_statement_target_table(statement) != table_name for statement in reverse_sql_statements
        ):
            return False
        return True

    def _sql_statement_target_table(self, statement: str) -> str | None:
        normalized_statement = statement.replace('"', "").strip()

        for table_regex in (_SQL_DROP_TABLE_RE, _SQL_CREATE_TABLE_RE, _SQL_ALTER_TABLE_RE):
            match = table_regex.match(normalized_statement)
            if match is not None:
                return self._normalize_db_table_name(match.group("table"))

        return None

    def _runsql_drop_table_if_exists_target(self, operation: Any) -> str | None:
        if operation.__class__.__name__ != "RunSQL":
            return None

        statements = list(self._iter_sql_statements(getattr(operation, "sql", None)))
        if len(statements) != 1:
            return None

        statement = statements[0].replace('"', "")
        match = _SQL_DROP_TABLE_IF_EXISTS_RE.match(statement)
        if match is None:
            return None

        return self._normalize_db_table_name(match.group("table"))

    def _runsql_drop_index_if_exists_target(self, operation: Any) -> str | None:
        if operation.__class__.__name__ != "RunSQL":
            return None

        statements = list(self._iter_sql_statements(getattr(operation, "sql", None)))
        if len(statements) != 1:
            return None

        statement = statements[0].replace('"', "")
        match = _SQL_DROP_INDEX_IF_EXISTS_RE.match(statement)
        if match is None:
            return None
        return str(match.group("index")).strip()

    def _fk_field_name_from_auto_index(self, index_name: str, table_name: str) -> str | None:
        normalized_index = index_name.strip()
        normalized_table = self._normalize_db_table_name(table_name)
        table_prefix = f"{normalized_table}_"
        if not normalized_index.startswith(table_prefix):
            return None

        tail = normalized_index[len(table_prefix) :]
        if "_" not in tail:
            return None

        column_name, _hash = tail.rsplit("_", 1)
        if not column_name.endswith("_id"):
            return None

        return column_name[:-3]

    def _set_create_model_field_db_index_false(self, create_model_operation: Any, field_name: str) -> bool:
        fields = getattr(create_model_operation, "fields", [])
        for existing_field_name, field in fields:
            if existing_field_name != field_name:
                continue
            if not hasattr(field, "remote_field"):
                return False
            remote_field = getattr(field, "remote_field", None)
            if remote_field is None:
                return False
            if getattr(field, "db_index", None) is False:
                return True
            field.db_index = False
            return True
        return False

    def _model_db_table_name(self, create_model_operation: Any) -> str:
        options = getattr(create_model_operation, "options", None)
        db_table = None
        if isinstance(options, dict):
            db_table = options.get("db_table")

        if db_table:
            return self._normalize_db_table_name(str(db_table))

        model_name = getattr(create_model_operation, "name", "")
        return self._normalize_db_table_name(f"{self.app_label}_{str(model_name).lower()}")

    @staticmethod
    def _normalize_db_table_name(table_name: str) -> str:
        normalized = table_name.strip().replace('"', "")
        if "." in normalized:
            normalized = normalized.split(".")[-1]
        return normalized.lower()

    def _rename_index_in_create_model(self, create_model_operation: Any, old_name: str, new_name: str) -> bool:
        options = getattr(create_model_operation, "options", None)
        if not isinstance(options, dict):
            return False

        indexes = options.get("indexes")
        if not isinstance(indexes, list):
            return False

        for index in indexes:
            if getattr(index, "name", None) == old_name:
                index.name = new_name
                return True
        return False

    def _rewrite_operation_for_bootstrap(self, operation: Any):
        op_type = operation.__class__.__name__

        if op_type == "AddIndexConcurrently":
            return migrations.AddIndex(model_name=operation.model_name, index=operation.index)
        if op_type == "RemoveIndexConcurrently":
            return migrations.RemoveIndex(model_name=operation.model_name, name=operation.name)
        if op_type == "RunSQL":
            return migrations.RunSQL(
                sql=self._strip_concurrently_from_sql_value(getattr(operation, "sql", None)),
                reverse_sql=self._strip_concurrently_from_sql_value(getattr(operation, "reverse_sql", None)),
                state_operations=getattr(operation, "state_operations", None),
                hints=getattr(operation, "hints", None),
                elidable=getattr(operation, "elidable", False),
            )
        if op_type == "SeparateDatabaseAndState":
            return migrations.SeparateDatabaseAndState(
                database_operations=[
                    self._rewrite_operation_for_bootstrap(nested_op)
                    for nested_op in getattr(operation, "database_operations", [])
                ],
                state_operations=[
                    self._rewrite_operation_for_bootstrap(nested_op)
                    for nested_op in getattr(operation, "state_operations", [])
                ],
            )
        return operation

    def _strip_concurrently_from_sql_value(self, sql_value: Any):
        if sql_value is None or sql_value is migrations.RunSQL.noop:
            return sql_value
        if isinstance(sql_value, str):
            return _SQL_CONCURRENTLY_RE.sub("", sql_value)
        if isinstance(sql_value, list):
            return [self._strip_concurrently_from_sql_value(item) for item in sql_value]
        if isinstance(sql_value, tuple):
            if len(sql_value) == 2 and isinstance(sql_value[0], str):
                return (self._strip_concurrently_from_sql_value(sql_value[0]), sql_value[1])
            return tuple(self._strip_concurrently_from_sql_value(item) for item in sql_value)
        return sql_value

    def _requested_span(self, start_name: str, end_name: str) -> list[str]:
        path = self._app_path_to_target(end_name)
        start_name_for_path = start_name
        if start_name_for_path not in path:
            resolved_start = self._resolve_graph_node((self.app_label, start_name))
            if resolved_start is not None and resolved_start[0] == self.app_label:
                start_name_for_path = resolved_start[1]

        end_name_for_path = end_name
        if end_name_for_path not in path:
            resolved_end = self._resolve_graph_node((self.app_label, end_name))
            if resolved_end is not None and resolved_end[0] == self.app_label:
                end_name_for_path = resolved_end[1]

        if start_name_for_path not in path:
            raise ValueError(
                f"Start migration '{self.app_label}.{start_name}' is not on the path to '{self.app_label}.{end_name}'."
            )
        if end_name_for_path not in path:
            raise ValueError(
                f"End migration '{self.app_label}.{end_name}' is not on the path for app '{self.app_label}'."
            )
        start_idx = path.index(start_name_for_path)
        end_idx = path.index(end_name_for_path)
        if start_idx > end_idx:
            raise ValueError(
                f"Start migration '{self.app_label}.{start_name}' comes after end migration '{self.app_label}.{end_name}'."
            )
        return path[start_idx : end_idx + 1]

    def _app_path_to_target(self, target_name: str) -> list[str]:
        target = (self.app_label, target_name)
        if target not in self.loader.graph.nodes:
            resolved_target = self._resolve_graph_node(target)
            if resolved_target is None:
                raise ValueError(f"Unknown migration '{self.app_label}.{target_name}'.")
            target = resolved_target
        return [name for app, name in self.loader.graph.forwards_plan(target) if app == self.app_label]

    def _flatten_operations(self, keys: list[tuple[str, str]]) -> list[Any]:
        operations: list[Any] = []
        for key in keys:
            migration = self.loader.disk_migrations[key]
            for op_index, operation in enumerate(migration.operations, start=1):
                operations.append(
                    self._rewrite_operation_for_policy(
                        migration_name=migration.name,
                        operation_index=op_index,
                        operation=operation,
                    )
                )
        return operations

    def _collect_dependencies(self, keys: list[tuple[str, str]]) -> list[tuple[str, str]]:
        included = set(keys)
        dependencies: set[tuple[str, str]] = set()
        for key in keys:
            migration = self.loader.disk_migrations[key]
            for dependency in migration.dependencies:
                if dependency not in included:
                    resolved_dependency = self._resolve_graph_node(dependency)
                    if resolved_dependency is None:
                        raise ValueError(
                            f"Could not resolve dependency '{dependency[0]}.{dependency[1]}' in migration "
                            f"'{migration.app_label}.{migration.name}'."
                        )
                    dependencies.add(resolved_dependency)
        return sorted(dependencies)

    def _requires_non_atomic(self, optimized_operations: list[Any]) -> bool:
        return any(self._operation_requires_non_atomic(operation) for operation in optimized_operations)

    def _operation_requires_non_atomic(self, operation: Any) -> bool:
        op_type = operation.__class__.__name__
        if op_type in {"AddIndexConcurrently", "RemoveIndexConcurrently"}:
            return True

        if op_type == "RunSQL":
            sql_statements = list(self._iter_sql_statements(getattr(operation, "sql", None)))
            reverse_sql_statements = list(self._iter_sql_statements(getattr(operation, "reverse_sql", None)))
            statements = sql_statements + reverse_sql_statements
            return any(" CONCURRENTLY " in f" {statement.upper()} " for statement in statements)

        if op_type == "SeparateDatabaseAndState":
            database_requires = any(
                self._operation_requires_non_atomic(nested_op)
                for nested_op in getattr(operation, "database_operations", [])
            )
            state_requires = any(
                self._operation_requires_non_atomic(nested_op)
                for nested_op in getattr(operation, "state_operations", [])
            )
            return database_requires or state_requires

        return False

    def _find_blockers_for_migration(self, migration_name: str, migration) -> list[OperationBlocker]:
        blockers: list[OperationBlocker] = []
        for idx, operation in enumerate(migration.operations):
            blockers.extend(
                self._find_blockers_for_operation(
                    migration_name=migration_name,
                    operation_index=idx + 1,
                    operation=operation,
                    nested_path=(),
                )
            )
        return blockers

    def _find_blockers_for_operation(
        self,
        migration_name: str,
        operation_index: int,
        operation,
        nested_path: tuple[tuple[str, int], ...] = (),
    ) -> list[OperationBlocker]:
        op_type = operation.__class__.__name__
        op_module = operation.__class__.__module__
        nested_path_str = self._format_nested_path(nested_path)
        operation_fingerprint = self._operation_fingerprint(operation)

        policy_resolution = self.bootstrap_policy.resolve(
            app_label=self.app_label,
            migration=migration_name,
            operation_index=operation_index,
            nested_path=nested_path_str,
            fingerprint=operation_fingerprint,
        )
        if policy_resolution is not None:
            if policy_resolution.action == "keep":
                return []
            if policy_resolution.action == "noop":
                if op_type in {"RunPython", "RunSQL"}:
                    return []
                return [
                    OperationBlocker(
                        migration=migration_name,
                        operation_index=operation_index,
                        operation_type=op_type,
                        reason=("Bootstrap policy action 'noop' is only supported for RunPython/RunSQL operations."),
                        nested_path=nested_path_str,
                        fingerprint=operation_fingerprint,
                    )
                ]
            if policy_resolution.action == "noop_if_empty":
                if not policy_resolution.tables:
                    return [
                        OperationBlocker(
                            migration=migration_name,
                            operation_index=operation_index,
                            operation_type=op_type,
                            reason="Bootstrap policy action 'noop_if_empty' requires non-empty table probes.",
                            nested_path=nested_path_str,
                            fingerprint=operation_fingerprint,
                        )
                    ]
                if op_type in {"RunPython", "RunSQL"}:
                    return []
                return [
                    OperationBlocker(
                        migration=migration_name,
                        operation_index=operation_index,
                        operation_type=op_type,
                        reason=(
                            "Bootstrap policy action 'noop_if_empty' is only supported for RunPython/RunSQL operations."
                        ),
                        nested_path=nested_path_str,
                        fingerprint=operation_fingerprint,
                    )
                ]
            return [
                OperationBlocker(
                    migration=migration_name,
                    operation_index=operation_index,
                    operation_type=op_type,
                    reason=f"Unsupported bootstrap policy action '{policy_resolution.action}'.",
                    nested_path=nested_path_str,
                    fingerprint=operation_fingerprint,
                )
            ]

        if op_type in self.allow_operation_types:
            return []

        if op_type in self.OPAQUE_OPERATION_TYPES:
            if op_type == "RunSQL" and self._is_schema_safe_runsql(operation):
                return []
            return [
                OperationBlocker(
                    migration=migration_name,
                    operation_index=operation_index,
                    operation_type=op_type,
                    reason="Opaque operation type requires manual review before squashing.",
                    nested_path=nested_path_str,
                    fingerprint=operation_fingerprint,
                )
            ]

        if op_type == "SeparateDatabaseAndState":
            blockers: list[OperationBlocker] = []
            for nested_idx, nested_op in enumerate(getattr(operation, "database_operations", [])):
                blockers.extend(
                    self._find_blockers_for_operation(
                        migration_name=migration_name,
                        operation_index=operation_index,
                        operation=nested_op,
                        nested_path=(*nested_path, ("database_operations", nested_idx)),
                    )
                )
            for nested_idx, nested_op in enumerate(getattr(operation, "state_operations", [])):
                blockers.extend(
                    self._find_blockers_for_operation(
                        migration_name=migration_name,
                        operation_index=operation_index,
                        operation=nested_op,
                        nested_path=(*nested_path, ("state_operations", nested_idx)),
                    )
                )
            return blockers

        if op_type not in self.SAFE_OPERATION_TYPES:
            return [
                OperationBlocker(
                    migration=migration_name,
                    operation_index=operation_index,
                    operation_type=op_type,
                    reason=f"Operation type '{op_type}' is outside the schema-safe allowlist.",
                    nested_path=nested_path_str,
                    fingerprint=operation_fingerprint,
                )
            ]

        if not op_module.startswith(self.SAFE_MODULE_PREFIXES):
            return [
                OperationBlocker(
                    migration=migration_name,
                    operation_index=operation_index,
                    operation_type=op_type,
                    reason=f"Operation module '{op_module}' is outside trusted Django migration modules.",
                    nested_path=nested_path_str,
                    fingerprint=operation_fingerprint,
                )
            ]

        migration_callables = self._operation_migration_callable_paths(operation)
        if migration_callables:
            return [
                OperationBlocker(
                    migration=migration_name,
                    operation_index=operation_index,
                    operation_type=op_type,
                    reason=(
                        "Operation references callable(s) defined in migration modules, "
                        "which cannot be safely serialized in squashed migrations: " + ", ".join(migration_callables)
                    ),
                    nested_path=nested_path_str,
                    fingerprint=operation_fingerprint,
                )
            ]

        return []

    def _verify_state_equivalence(
        self,
        included_keys: list[tuple[str, str]],
        optimized_operations: list[Any],
    ) -> tuple[bool, list[str]]:
        first_migration = self.loader.disk_migrations[included_keys[0]]
        resolved_dependencies: list[tuple[str, str]] = []
        for dependency in first_migration.dependencies:
            resolved_dependency = self._resolve_graph_node(dependency)
            if resolved_dependency is None:
                return False, [
                    f"Unable to resolve dependency '{dependency[0]}.{dependency[1]}' while building pre-squash state."
                ]
            resolved_dependencies.append(resolved_dependency)

        base_state = self.loader.project_state(resolved_dependencies)
        original_state = base_state.clone()
        squashed_state = base_state.clone()

        for key in included_keys:
            migration = self.loader.disk_migrations[key]
            for operation in migration.operations:
                operation.state_forwards(migration.app_label, original_state)

        for operation in optimized_operations:
            operation.state_forwards(self.app_label, squashed_state)

        normalized_original = self._normalize_app_state(original_state)
        normalized_squashed = self._normalize_app_state(squashed_state)

        if normalized_original == normalized_squashed:
            return True, []

        differences: list[str] = []
        original_models = set(normalized_original.keys())
        squashed_models = set(normalized_squashed.keys())
        only_original = sorted(original_models - squashed_models)
        only_squashed = sorted(squashed_models - original_models)

        for model_name in only_original:
            differences.append(f"Model present only in original state: {model_name}")
        for model_name in only_squashed:
            differences.append(f"Model present only in squashed state: {model_name}")

        for model_name in sorted(original_models & squashed_models):
            if normalized_original[model_name] != normalized_squashed[model_name]:
                differences.append(f"Model differs after squash optimization: {model_name}")

        if not differences:
            differences.append("State mismatch detected but no specific model diff was identified.")

        return False, differences

    def _resolve_graph_node(self, dependency: tuple[str, str]) -> tuple[str, str] | None:
        if dependency in self.loader.graph.nodes:
            return dependency

        app_label, migration_name = dependency
        if migration_name == "__first__":
            roots = sorted(
                [node for node in self.loader.graph.root_nodes(app_label) if node[0] == app_label],
                key=lambda node: self._migration_sort_key(node[1]),
            )
            return roots[0] if roots else None

        if migration_name == "__latest__":
            leaves = sorted(
                [node for node in self.loader.graph.leaf_nodes(app_label) if node[0] == app_label],
                key=lambda node: self._migration_sort_key(node[1]),
            )
            return leaves[-1] if leaves else None

        for node, migration in self.loader.disk_migrations.items():
            if node not in self.loader.graph.nodes:
                continue
            replaces = getattr(migration, "replaces", []) or []
            if dependency in replaces:
                return node

        return None

    def _is_schema_safe_runsql(self, operation) -> bool:
        return self._all_sql_statements_safe(getattr(operation, "sql", None)) and self._all_sql_statements_safe(
            getattr(operation, "reverse_sql", None), allow_noop=True
        )

    def _all_sql_statements_safe(self, sql_value: Any, allow_noop: bool = False) -> bool:
        if allow_noop and self._is_noop_sql(sql_value):
            return True

        statements = list(self._iter_sql_statements(sql_value))
        if not statements:
            return False
        return all(self._is_safe_sql_statement(statement) for statement in statements)

    def _is_noop_sql(self, sql_value: Any) -> bool:
        return sql_value is migrations.RunSQL.noop

    def _iter_sql_statements(self, sql_value: Any):
        if sql_value is None:
            return
        if isinstance(sql_value, (list, tuple)):
            for item in sql_value:
                if isinstance(item, tuple):
                    # RunSQL accepts (sql, params) tuples in statement lists.
                    item = item[0]
                yield from self._iter_sql_statements(item)
            return
        if not isinstance(sql_value, str):
            return

        without_comments = _SQL_COMMENT_RE.sub("", sql_value)
        for statement in without_comments.split(";"):
            normalized = " ".join(statement.strip().split())
            if normalized:
                yield normalized

    def _is_safe_sql_statement(self, statement: str) -> bool:
        normalized = f" {statement.upper()} "
        if any(keyword in normalized for keyword in self.RUNSQL_DML_KEYWORDS):
            return False

        statement_upper = statement.upper()
        if statement_upper.startswith("CREATE INDEX") or statement_upper.startswith("CREATE UNIQUE INDEX"):
            return True
        if statement_upper.startswith("DROP INDEX") or statement_upper.startswith("REINDEX INDEX"):
            return True
        if statement_upper.startswith("CREATE EXTENSION") or statement_upper.startswith("DROP EXTENSION"):
            return True
        if statement_upper.startswith("COMMENT ON"):
            return True
        if statement_upper.startswith("ALTER TABLE"):
            return " CONSTRAINT " in statement_upper and (
                " ADD CONSTRAINT " in statement_upper
                or " DROP CONSTRAINT " in statement_upper
                or " VALIDATE CONSTRAINT " in statement_upper
            )

        return False

    def _normalize_app_state(self, state) -> dict[str, Any]:
        models = {
            model_name: model_state
            for (app_label, model_name), model_state in state.models.items()
            if app_label == self.app_label
        }
        return {model_name: self._normalize_model_state(models[model_name]) for model_name in sorted(models)}

    def _normalize_model_state(self, model_state) -> dict[str, Any]:
        fields_raw = model_state.fields.items() if isinstance(model_state.fields, dict) else model_state.fields
        normalized_fields = [
            (field_name, self._normalize_field(field_value))
            for field_name, field_value in sorted(fields_raw, key=lambda item: item[0])
        ]
        return {
            "name": model_state.name,
            "fields": normalized_fields,
            "options": self._normalize_value(model_state.options),
            "bases": self._normalize_value(model_state.bases),
            "managers": self._normalize_value(model_state.managers),
        }

    def _normalize_field(self, field: Any) -> Any:
        if hasattr(field, "deconstruct"):
            deconstructed = field.deconstruct()
            if isinstance(deconstructed, tuple) and len(deconstructed) == 4:
                _, path, args, kwargs = deconstructed
                return {
                    "path": path,
                    "args": self._normalize_value(args),
                    "kwargs": self._normalize_value(kwargs),
                }
        return self._normalize_value(field)

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        if isinstance(value, tuple):
            return tuple(self._normalize_value(item) for item in value)
        if isinstance(value, list):
            return [self._normalize_value(item) for item in value]
        if isinstance(value, set):
            return sorted(self._normalize_value(item) for item in value)
        if isinstance(value, dict):
            return {
                str(key): self._normalize_value(value[key]) for key in sorted(value.keys(), key=lambda item: str(item))
            }
        if hasattr(value, "deconstruct") and callable(value.deconstruct):
            deconstructed = value.deconstruct()
            if isinstance(deconstructed, tuple):
                if len(deconstructed) == 3:
                    path, args, kwargs = deconstructed
                elif len(deconstructed) == 4:
                    _, path, args, kwargs = deconstructed
                else:
                    return repr(value)
                return {
                    "path": path,
                    "args": self._normalize_value(args),
                    "kwargs": self._normalize_value(kwargs),
                }
        if isinstance(value, type):
            return f"{value.__module__}.{value.__qualname__}"
        if callable(value):
            module = getattr(value, "__module__", "")
            qualname = getattr(value, "__qualname__", getattr(value, "__name__", repr(value)))
            return f"{module}.{qualname}"
        return repr(value)

    def _inject_non_atomic_flag(self, rendered_migration: str) -> str:
        class_declaration = "class Migration(migrations.Migration):\n"
        atomic_declaration = "    atomic = False\n"
        if atomic_declaration in rendered_migration or class_declaration not in rendered_migration:
            return rendered_migration
        return rendered_migration.replace(class_declaration, f"{class_declaration}\n{atomic_declaration}", 1)

    def _operation_migration_callable_paths(self, operation) -> list[str]:
        if not hasattr(operation, "deconstruct"):
            return []

        deconstructed = operation.deconstruct()
        if not isinstance(deconstructed, tuple) or len(deconstructed) != 3:
            return []
        _, args, kwargs = deconstructed

        callables = self._migration_callable_paths_in_value(args)
        callables.update(self._migration_callable_paths_in_value(kwargs))
        return sorted(callables)

    def _migration_callable_paths_in_value(self, value: Any) -> set[str]:
        matches: set[str] = set()
        if isinstance(value, (str, int, float, bool, type(None), bytes)):
            return matches

        if isinstance(value, dict):
            for nested_value in value.values():
                matches.update(self._migration_callable_paths_in_value(nested_value))
            return matches

        if isinstance(value, (list, tuple, set, frozenset)):
            for nested_value in value:
                matches.update(self._migration_callable_paths_in_value(nested_value))
            return matches

        if hasattr(value, "deconstruct") and callable(value.deconstruct):
            deconstructed = value.deconstruct()
            if isinstance(deconstructed, tuple):
                if len(deconstructed) == 3:
                    _, args, kwargs = deconstructed
                    matches.update(self._migration_callable_paths_in_value(args))
                    matches.update(self._migration_callable_paths_in_value(kwargs))
                elif len(deconstructed) == 4:
                    _, _, args, kwargs = deconstructed
                    matches.update(self._migration_callable_paths_in_value(args))
                    matches.update(self._migration_callable_paths_in_value(kwargs))

        if callable(value):
            module = getattr(value, "__module__", "")
            if _MIGRATION_MODULE_CALLABLE_RE.search(module):
                qualname = getattr(value, "__qualname__", getattr(value, "__name__", repr(value)))
                matches.add(f"{module}.{qualname}")

        return matches

    def _format_nested_path(self, nested_path: tuple[tuple[str, int], ...]) -> str | None:
        if not nested_path:
            return None
        return ".".join(f"{segment}[{index}]" for segment, index in nested_path)

    def _operation_fingerprint(self, operation: Any) -> str:
        payload: dict[str, Any] = {
            "type": operation.__class__.__name__,
            "module": operation.__class__.__module__,
        }
        if hasattr(operation, "deconstruct"):
            deconstructed = operation.deconstruct()
            if isinstance(deconstructed, tuple) and len(deconstructed) == 3:
                name, args, kwargs = deconstructed
                payload["name"] = name
                payload["args"] = self._normalize_fingerprint_value(args)
                payload["kwargs"] = self._normalize_fingerprint_value(kwargs)
            else:
                payload["deconstruct_repr"] = repr(deconstructed)
        else:
            payload["repr"] = repr(operation)

        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        return f"sha256:{digest}"

    def _normalize_fingerprint_value(self, value: Any) -> Any:
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        if isinstance(value, tuple):
            return ["tuple", [self._normalize_fingerprint_value(item) for item in value]]
        if isinstance(value, list):
            return [self._normalize_fingerprint_value(item) for item in value]
        if isinstance(value, set):
            return ["set", sorted(self._normalize_fingerprint_value(item) for item in value)]
        if isinstance(value, dict):
            return {str(key): self._normalize_fingerprint_value(value[key]) for key in sorted(value.keys(), key=str)}
        if hasattr(value, "deconstruct") and callable(value.deconstruct):
            deconstructed = value.deconstruct()
            if isinstance(deconstructed, tuple):
                if len(deconstructed) == 3:
                    path, args, kwargs = deconstructed
                elif len(deconstructed) == 4:
                    _, path, args, kwargs = deconstructed
                else:
                    return repr(value)
                return {
                    "path": path,
                    "args": self._normalize_fingerprint_value(args),
                    "kwargs": self._normalize_fingerprint_value(kwargs),
                }
        if isinstance(value, type):
            return f"{value.__module__}.{value.__qualname__}"
        if callable(value):
            module = getattr(value, "__module__", "")
            qualname = getattr(value, "__qualname__", getattr(value, "__name__", repr(value)))
            return f"{module}.{qualname}"
        return repr(value)

    def _latest_replaced_migration(self) -> str | None:
        latest_name: str | None = None
        for (app, _name), migration in self.loader.disk_migrations.items():
            if app != self.app_label:
                continue
            for replaced_app, replaced_name in getattr(migration, "replaces", []) or []:
                if replaced_app != self.app_label:
                    continue
                if latest_name is None or self._migration_sort_key(replaced_name) > self._migration_sort_key(
                    latest_name
                ):
                    latest_name = replaced_name
        return latest_name

    def _read_max_migration_file(self) -> str | None:
        app_config = apps.get_app_config(self.app_label)
        max_migration_path = Path(app_config.path) / "migrations" / "max_migration.txt"
        if not max_migration_path.exists():
            return None
        value = max_migration_path.read_text().strip()
        return value or None

    @staticmethod
    def _migration_sort_key(name: str) -> tuple[int, str]:
        match = _MIGRATION_PREFIX_RE.match(name)
        prefix = int(match.group("prefix")) if match else 0
        return prefix, name

    @staticmethod
    def _migration_prefix(name: str) -> str:
        match = _MIGRATION_PREFIX_RE.match(name)
        if match:
            return match.group("prefix")
        return name

    @staticmethod
    def _normalize_suffix(name: str) -> str:
        normalized = _SQUASH_SUFFIX_RE.sub("_", name.strip().lower())
        normalized = normalized.strip("_")
        return normalized or "squash"
