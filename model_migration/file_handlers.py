"""File handlers for different migration strategies in no-merge mode."""

import logging
from pathlib import Path
from typing import Protocol

import libcst as cst

logger = logging.getLogger(__name__)


class FileTransformContext:
    """Context data needed for file transformations."""

    def __init__(
        self,
        model_names: set[str],
        target_app: str,
        import_base_path: str,
        source_base_path: str,
        root_dir: Path,
        model_to_filename_mapping: dict[str, str],
    ):
        self.model_names = model_names
        self.target_app = target_app
        self.import_base_path = import_base_path
        self.source_base_path = source_base_path
        self.root_dir = root_dir
        self.model_to_filename_mapping = model_to_filename_mapping


class FileHandler(Protocol):
    """Protocol for file handlers that process files during migration."""

    def process_file(
        self,
        source_file: str,
        source_path: Path,
        models_dir: Path,
        context: FileTransformContext,
        foreign_key_updater,
        libcst_transformer_class,
        db_table_ensurer,
    ) -> Path | None:
        """Process a file and return the target path, or None if skipped."""
        ...


class DirectoryPreservingHandler:
    """Handler that preserves full directory structure (for directory mode).

    Example:
        models/table.py → backend/models/models/table.py
        api/saved_query.py → backend/models/api/saved_query.py
        data_load/service.py → backend/models/data_load/service.py
    """

    def process_file(
        self,
        source_file: str,
        source_path: Path,
        models_dir: Path,
        context: FileTransformContext,
        foreign_key_updater,
        libcst_transformer_class,
        db_table_ensurer,
    ) -> Path | None:
        """Process file while preserving full directory structure."""
        if not source_path.exists():
            logger.warning("⚠️  Source file not found: %s", source_path)
            return None

        # Preserve full directory structure
        # e.g., models/table.py → models/models/table.py
        # e.g., api/saved_query.py → models/api/saved_query.py
        target_file_path = models_dir / source_file

        # Create parent directories if needed
        target_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Read and process the source file
        content = source_path.read_text()

        # Update foreign key references
        lines = content.split("\n")
        updated_lines = []
        for line in lines:
            updated_line = foreign_key_updater(line, context.model_names)
            updated_lines.append(updated_line)
        updated_content = "\n".join(updated_lines)

        # Apply LibCST transformation to update internal imports
        try:
            tree = cst.parse_module(updated_content)
            module_name = source_file.replace(".py", "")
            transformer = libcst_transformer_class(
                context.model_names,
                context.target_app,
                module_name,
                merge_models=False,  # We're in no-merge mode
                import_base_path=context.import_base_path,
                filename_to_model_mapping=context.model_to_filename_mapping,
            )
            new_tree = tree.visit(transformer)
            updated_content = new_tree.code
        except Exception as e:
            logger.warning("⚠️  LibCST transformation failed for %s: %s", source_file, e)
            # Continue with FK-updated content

        # Write to target
        target_file_path.write_text(updated_content)

        # Ensure db_table for Django model files
        if source_file.startswith("models/"):
            db_table_ensurer(target_file_path)

        logger.info("📄 Moved %s → %s", source_file, target_file_path.relative_to(context.root_dir))
        return target_file_path
