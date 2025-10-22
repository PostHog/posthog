#!/usr/bin/env python3
"""
Import pattern matching and transformation for model migrations.
Separates the concerns of identifying import patterns from transforming them.
"""

import re
from dataclasses import dataclass
from typing import Protocol

import libcst as cst


@dataclass
class ImportParts:
    """Parts extracted from an import statement"""

    imported_names: list[str]  # The names being imported
    source_file: str | None  # The specific file they come from (if any)
    module_path: str  # The original module path (e.g., "posthog.warehouse.models")


@dataclass
class MigrationContext:
    """Context information for the migration"""

    model_names: set[str]  # Model class names being migrated
    import_base_path: str  # e.g., "posthog.warehouse.models"
    module_name: str  # e.g., "external_data_source" or "warehouse/table"
    target_app: str  # e.g., "data_warehouse"
    merge_models: bool  # Whether to merge into models.py
    filename_to_model_mapping: dict[str, str]  # Maps model names to filenames


class ImportPattern(Protocol):
    """Protocol for import pattern matchers"""

    def matches(self, node: cst.ImportFrom, context: MigrationContext) -> bool:
        """Check if this pattern matches the import node"""
        ...

    def extract_parts(self, node: cst.ImportFrom, context: MigrationContext) -> ImportParts:
        """Extract the relevant parts from the import"""
        ...


class PackageLevelImport:
    """Matches: from posthog.warehouse.models import X, Y, Z"""

    def matches(self, node: cst.ImportFrom, context: MigrationContext) -> bool:
        if not node.module:
            return False

        module_str = self._get_module_string(node.module)
        return module_str == context.import_base_path

    def extract_parts(self, node: cst.ImportFrom, context: MigrationContext) -> ImportParts:
        if not node.names or isinstance(node.names, cst.ImportStar):
            return ImportParts(imported_names=[], source_file=None, module_path=context.import_base_path)

        imported_names = []
        for name in node.names:
            if isinstance(name, cst.ImportAlias):
                imported_names.append(name.name.value)

        # Package-level imports have no specific source file
        return ImportParts(imported_names=imported_names, source_file=None, module_path=context.import_base_path)

    @staticmethod
    def _get_module_string(module: cst.CSTNode) -> str:
        if isinstance(module, cst.Name):
            return module.value
        elif isinstance(module, cst.Attribute):
            return f"{PackageLevelImport._get_module_string(module.value)}.{module.attr.value}"
        else:
            return cst.Module(body=[cst.SimpleStatementLine(body=[cst.Expr(value=module)])]).code.strip()


class FileSpecificImport:
    """Matches: from posthog.warehouse.models.external_data_schema import X, Y"""

    def matches(self, node: cst.ImportFrom, context: MigrationContext) -> bool:
        if not node.module:
            return False

        module_str = self._get_module_string(node.module)

        # Determine the base path to check against
        if "/" in context.module_name:
            # Subdirectory case: posthog.warehouse.models.file
            subdirectory_name = context.module_name.split("/")[0]
            base_path = f"{context.import_base_path}.{subdirectory_name}"
        else:
            # Direct file case: posthog.models.file
            base_path = f"{context.import_base_path}.{context.module_name}"

        # Match if it starts with base_path and has a file-specific part
        return module_str.startswith(base_path + ".")

    def extract_parts(self, node: cst.ImportFrom, context: MigrationContext) -> ImportParts:
        if not node.names or isinstance(node.names, cst.ImportStar):
            return ImportParts(imported_names=[], source_file=None, module_path="")

        imported_names = []
        for name in node.names:
            if isinstance(name, cst.ImportAlias):
                imported_names.append(name.name.value)

        module_str = self._get_module_string(node.module)

        # Extract the file-specific part
        if "/" in context.module_name:
            subdirectory_name = context.module_name.split("/")[0]
            base_path = f"{context.import_base_path}.{subdirectory_name}"
        else:
            base_path = f"{context.import_base_path}.{context.module_name}"

        if module_str.startswith(base_path + "."):
            # Extract everything after base_path (e.g., ".external_data_schema")
            file_part = module_str[len(base_path) + 1 :]  # +1 to skip the dot
            return ImportParts(imported_names=imported_names, source_file=file_part, module_path=module_str)

        # Shouldn't happen if matches() returned True, but handle gracefully
        return ImportParts(imported_names=imported_names, source_file=None, module_path=module_str)

    @staticmethod
    def _get_module_string(module: cst.CSTNode) -> str:
        if isinstance(module, cst.Name):
            return module.value
        elif isinstance(module, cst.Attribute):
            return f"{FileSpecificImport._get_module_string(module.value)}.{module.attr.value}"
        else:
            return cst.Module(body=[cst.SimpleStatementLine(body=[cst.Expr(value=module)])]).code.strip()


class ModelsPackageLevelImport:
    """Matches imports from {import_base_path}.models (the models package).

    For example: from posthog.warehouse.models import X

    This is a special case - "models" is a package directory, not a file,
    so in no-merge mode we need to look up which file X comes from.
    This pattern must be checked BEFORE AnyFileSpecificImport to prevent
    treating "models" as a filename.
    """

    def matches(self, node: cst.ImportFrom, context: MigrationContext) -> bool:
        if not node.module:
            return False

        module_str = self._get_module_string(node.module)
        return module_str == f"{context.import_base_path}.models"

    def extract_parts(self, node: cst.ImportFrom, context: MigrationContext) -> ImportParts:
        if not node.names or isinstance(node.names, cst.ImportStar):
            return ImportParts(imported_names=[], source_file=None, module_path="")

        imported_names = []
        for name in node.names:
            if isinstance(name, cst.ImportAlias):
                imported_names.append(name.name.value)

        module_str = self._get_module_string(node.module)

        # Return with source_file=None so the resolver will look up each name
        return ImportParts(imported_names=imported_names, source_file=None, module_path=module_str)

    @staticmethod
    def _get_module_string(module: cst.CSTNode) -> str:
        if isinstance(module, cst.Name):
            return module.value
        elif isinstance(module, cst.Attribute):
            return f"{ModelsPackageLevelImport._get_module_string(module.value)}.{module.attr.value}"
        else:
            return cst.Module(body=[cst.SimpleStatementLine(body=[cst.Expr(value=module)])]).code.strip()


class AnyFileSpecificImport:
    """Matches ANY file-specific import from the import_base_path.

    For example: from posthog.warehouse.models.external_data_job import X

    This is needed when moving files that import OTHER files from the same base path.
    """

    def matches(self, node: cst.ImportFrom, context: MigrationContext) -> bool:
        if not node.module:
            return False

        module_str = self._get_module_string(node.module)

        # Match if it starts with import_base_path followed by a dot and filename
        # e.g., "posthog.warehouse.models.external_data_job"
        return module_str.startswith(context.import_base_path + ".")

    def extract_parts(self, node: cst.ImportFrom, context: MigrationContext) -> ImportParts:
        if not node.names or isinstance(node.names, cst.ImportStar):
            return ImportParts(imported_names=[], source_file=None, module_path="")

        imported_names = []
        for name in node.names:
            if isinstance(name, cst.ImportAlias):
                imported_names.append(name.name.value)

        module_str = self._get_module_string(node.module)

        # Extract the file-specific part after import_base_path
        # e.g., "posthog.warehouse.models.external_data_job" -> "external_data_job"
        if module_str.startswith(context.import_base_path + "."):
            file_part = module_str[len(context.import_base_path) + 1 :]  # +1 to skip the dot
            return ImportParts(imported_names=imported_names, source_file=file_part, module_path=module_str)

        return ImportParts(imported_names=imported_names, source_file=None, module_path=module_str)

    @staticmethod
    def _get_module_string(module: cst.CSTNode) -> str:
        if isinstance(module, cst.Name):
            return module.value
        elif isinstance(module, cst.Attribute):
            return f"{AnyFileSpecificImport._get_module_string(module.value)}.{module.attr.value}"
        else:
            return cst.Module(body=[cst.SimpleStatementLine(body=[cst.Expr(value=module)])]).code.strip()


class ImportTargetResolver:
    """Resolves target paths for imports based on merge_models setting"""

    def __init__(self, context: MigrationContext):
        self.context = context

    def resolve_target(self, parts: ImportParts, import_name: str | None = None) -> str:
        """
        Resolve the target module path for an import.

        Args:
            parts: The extracted import parts
            import_name: Specific name being imported (for no-merge lookup)

        Returns:
            Target module path (e.g., "products.data_warehouse.backend.models.external_data_schema")
        """
        if self.context.merge_models:
            # Merge mode: everything goes to products.app.backend.models
            # (except sub-modules like .sql which are preserved)
            return f"products.{self.context.target_app}.backend.models"
        else:
            # No-merge mode: file-specific imports
            if parts.source_file:
                # Already have the file - use it
                return f"products.{self.context.target_app}.backend.models.{parts.source_file}"
            elif import_name:
                # Package-level import - look up which file this name comes from
                if import_name in self.context.filename_to_model_mapping:
                    filename = self.context.filename_to_model_mapping[import_name]
                else:
                    # Fallback: convert to snake_case
                    filename = self._to_snake_case(import_name)
                return f"products.{self.context.target_app}.backend.models.{filename}"
            else:
                # No source file and no specific import name - shouldn't happen
                return f"products.{self.context.target_app}.backend.models"

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert CamelCase to snake_case"""
        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
