"""File handlers for different migration strategies in no-merge mode."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

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


class BaseFileHandler(ABC):
    """Base handler with common transformation logic."""

    def __init__(self, context: FileTransformContext):
        self.context = context

    @abstractmethod
    def compute_target_path(self, source_file: str, backend_dir: Path) -> Path:
        """Compute target path for the source file."""
        ...

    @abstractmethod
    def should_apply_db_table(self, source_file: str) -> bool:
        """Determine if db_table should be applied to this file."""
        ...

    def apply_transformations(
        self,
        content: str,
        source_file: str,
        foreign_key_updater,
        libcst_transformer_class,
    ) -> str:
        """Apply FK updates and LibCST transformations to file content."""
        # Update foreign key references
        lines = content.split("\n")
        updated_lines = []
        for line in lines:
            updated_line = foreign_key_updater(line, self.context.model_names)
            updated_lines.append(updated_line)
        updated_content = "\n".join(updated_lines)

        # Apply LibCST transformation to update internal imports
        try:
            tree = cst.parse_module(updated_content)
            module_name = source_file.replace(".py", "")
            transformer = libcst_transformer_class(
                self.context.model_names,
                self.context.target_app,
                module_name,
                merge_models=False,  # We're in no-merge mode
                import_base_path=self.context.import_base_path,
                filename_to_model_mapping=self.context.model_to_filename_mapping,
            )
            new_tree = tree.visit(transformer)
            updated_content = new_tree.code
        except Exception as e:
            logger.warning("⚠️  LibCST transformation failed for %s: %s", source_file, e)
            # Continue with FK-updated content

        return updated_content

    def process_file(
        self,
        source_file: str,
        source_path: Path,
        backend_dir: Path,
        foreign_key_updater,
        libcst_transformer_class,
        db_table_ensurer,
    ) -> Path | None:
        """Process a file and return the target path, or None if skipped."""
        if not source_path.exists():
            logger.warning("⚠️  Source file not found: %s", source_path)
            return None

        # Compute target path using subclass logic
        target_file_path = self.compute_target_path(source_file, backend_dir)

        # Debug logging to show path transformation
        logger.info("   📂 Source: %s", source_path.relative_to(self.context.root_dir))
        logger.info("   📂 Target: %s", target_file_path.relative_to(self.context.root_dir))

        # Create parent directories if needed
        target_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Read and process the source file
        content = source_path.read_text()

        # Apply transformations
        updated_content = self.apply_transformations(
            content, source_file, foreign_key_updater, libcst_transformer_class
        )

        # Write to target
        target_file_path.write_text(updated_content)

        # Ensure db_table for Django model files if applicable
        if self.should_apply_db_table(source_file):
            logger.info("   ✅ Applying db_table to %s", source_file)
            db_table_ensurer(target_file_path)

        logger.info("   ✅ Completed: %s → %s", source_file, target_file_path.relative_to(self.context.root_dir))
        return target_file_path


class ModelsDirectoryHandler(BaseFileHandler):
    """Handler for files from models/ directory.

    Strips the models/ prefix and writes to backend/models/.

    Example:
        models/table.py → backend/models/table.py
        models/saved_query.py → backend/models/saved_query.py
    """

    def compute_target_path(self, source_file: str, backend_dir: Path) -> Path:
        """Strip models/ prefix and write to backend/models/."""
        relative_path = Path(source_file).relative_to("models")
        return backend_dir / "models" / relative_path

    def should_apply_db_table(self, source_file: str) -> bool:
        """Apply db_table to files from models/ directory."""
        return True


class DefaultFileHandler(BaseFileHandler):
    """Handler for all non-models files.

    Preserves the directory structure at backend level.

    Examples:
        api/saved_query.py → backend/api/saved_query.py
        data_load/service.py → backend/data_load/service.py
        hogql.py → backend/hogql.py
        s3.py → backend/s3.py
    """

    def compute_target_path(self, source_file: str, backend_dir: Path) -> Path:
        """Preserve file structure at backend level."""
        return backend_dir / source_file

    def should_apply_db_table(self, source_file: str) -> bool:
        """Do not apply db_table to non-model files."""
        return False


class HandlerFactory:
    """Factory to create appropriate handler based on source file path."""

    @staticmethod
    def create_handler(source_file: str, context: FileTransformContext) -> BaseFileHandler:
        """Create appropriate handler based on source file path."""
        source_path = Path(source_file)

        # Check if file is in models/ directory
        if source_path.parts[0] == "models":
            logger.info("🔧 Handler: ModelsDirectoryHandler for %s (strips models/ prefix)", source_file)
            return ModelsDirectoryHandler(context)

        # All other files - preserve structure at backend level
        logger.info("🔧 Handler: DefaultFileHandler for %s (preserves structure at backend/)", source_file)
        return DefaultFileHandler(context)
