#!/usr/bin/env python3
"""
Unified shim removal: Ripgrep for speed + LibCST for safety.
Uses ripgrep to find files, LibCST to transform imports properly.
"""

import logging
import subprocess
from pathlib import Path

import libcst as cst

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Shim mappings: model_name -> direct_import_path
SHIM_MAPPINGS = {
    "EarlyAccessFeature": "products.early_access_features.backend.models",
    "Dataset": "products.llm_analytics.backend.models",
    "DatasetItem": "products.llm_analytics.backend.models",
    "Task": "products.tasks.backend.models",
}


def find_files_with_ripgrep() -> list[str]:
    """Use ripgrep to find files with posthog.models imports"""
    try:
        result = subprocess.run(
            ["rg", "-l", "from posthog\\.models import", "--type", "py"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        return []


class ImportRewriter(cst.CSTTransformer):
    """Transform imports from posthog.models to direct product imports"""

    def __init__(self):
        self.imports_changed = False
        self.new_imports_to_add: list[cst.SimpleStatementLine] = []

    def visit_Module(self, node: cst.Module) -> None:
        self.new_imports_to_add = []

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        """Add new imports right after the last existing import"""
        if not self.new_imports_to_add:
            return updated_node

        # Find the last import statement
        last_import_index = -1
        for i, stmt in enumerate(updated_node.body):
            if self._is_import_statement(stmt):
                last_import_index = i

        if last_import_index >= 0:
            # Insert after last import
            new_body = (
                list(updated_node.body[: last_import_index + 1])
                + self.new_imports_to_add
                + list(updated_node.body[last_import_index + 1 :])
            )
        else:
            # No imports found, add at beginning
            new_body = self.new_imports_to_add + list(updated_node.body)

        return updated_node.with_changes(body=new_body)

    def leave_SimpleStatementLine(self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine):
        """Handle import statements"""
        if not isinstance(updated_node.body[0], cst.ImportFrom):
            return updated_node

        import_from = updated_node.body[0]
        if not self._is_posthog_models_import(import_from):
            return updated_node

        # Extract imported names
        imported_names = self._extract_imported_names(import_from)
        if not imported_names:
            return updated_node

        # Separate shimmed vs non-shimmed imports
        shimmed_models = {}
        non_shimmed = []

        for name in imported_names:
            if name in SHIM_MAPPINGS:
                import_path = SHIM_MAPPINGS[name]
                if import_path not in shimmed_models:
                    shimmed_models[import_path] = []
                shimmed_models[import_path].append(name)
            else:
                non_shimmed.append(name)

        if not shimmed_models:
            return updated_node

        # Create direct imports for shimmed models
        for import_path, models in shimmed_models.items():
            direct_import = self._create_direct_import(import_path, models)
            self.new_imports_to_add.append(cst.SimpleStatementLine([direct_import]))

        self.imports_changed = True
        logging.info(f"  🔄 Updated import: {', '.join(sum(shimmed_models.values(), []))} → direct imports")

        # Keep non-shimmed imports or remove line entirely
        if non_shimmed:
            new_import = self._create_posthog_models_import(non_shimmed)
            return updated_node.with_changes(body=[new_import])
        else:
            return cst.RemovalSentinel.REMOVE

    def _is_posthog_models_import(self, import_from: cst.ImportFrom) -> bool:
        if import_from.module is None:
            return False
        module_code = cst.Module([cst.SimpleStatementLine([cst.Expr(import_from.module)])]).code.strip()
        return module_code == "posthog.models"

    def _extract_imported_names(self, import_from: cst.ImportFrom) -> list[str]:
        if import_from.names is None or isinstance(import_from.names, cst.ImportStar):
            return []
        return [name.name.value for name in import_from.names if isinstance(name, cst.ImportAlias)]

    def _create_posthog_models_import(self, names: list[str]) -> cst.ImportFrom:
        import_names = [cst.ImportAlias(cst.Name(name)) for name in sorted(names)]
        return cst.ImportFrom(
            module=cst.Attribute(value=cst.Name("posthog"), attr=cst.Name("models")),
            names=import_names,
        )

    def _create_direct_import(self, import_path: str, models: list[str]) -> cst.ImportFrom:
        path_parts = import_path.split(".")
        module = cst.Name(path_parts[0])
        for part in path_parts[1:]:
            module = cst.Attribute(value=module, attr=cst.Name(part))

        import_names = [cst.ImportAlias(cst.Name(name)) for name in sorted(models)]
        return cst.ImportFrom(module=module, names=import_names)

    def _is_import_statement(self, stmt: cst.BaseStatement) -> bool:
        if isinstance(stmt, cst.SimpleStatementLine):
            return isinstance(stmt.body[0], cst.Import | cst.ImportFrom)
        return False


class ShimRemover(cst.CSTTransformer):
    """Remove shim imports from posthog/models/__init__.py"""

    def __init__(self, models_to_remove: set[str]):
        self.models_to_remove = models_to_remove
        self.removals_made = False

    def leave_SimpleStatementLine(self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine):
        if not isinstance(updated_node.body[0], cst.ImportFrom):
            return updated_node

        import_from = updated_node.body[0]
        if not self._is_product_import(import_from):
            return updated_node

        imported_names = self._extract_imported_names(import_from)
        models_in_import = set(imported_names) & self.models_to_remove

        if models_in_import:
            self.removals_made = True
            logging.info(f"  ❌ Removed shim import: {', '.join(models_in_import)}")
            return cst.RemovalSentinel.REMOVE

        return updated_node

    def leave_List(self, original_node: cst.List, updated_node: cst.List) -> cst.List:
        """Remove shimmed models from __all__ list"""
        new_elements = []
        for elem in updated_node.elements:
            if isinstance(elem, cst.Element) and isinstance(elem.value, cst.SimpleString):
                string_value = elem.value.value.strip("\"'")
                if string_value not in self.models_to_remove:
                    new_elements.append(elem)
                else:
                    logging.info(f"  ❌ Removed '{string_value}' from __all__")
            else:
                new_elements.append(elem)
        return updated_node.with_changes(elements=new_elements)

    def _is_product_import(self, import_from: cst.ImportFrom) -> bool:
        if import_from.module is None:
            return False
        module_str = cst.Module([cst.SimpleStatementLine([import_from])]).code
        return "from products." in module_str

    def _extract_imported_names(self, import_from: cst.ImportFrom) -> list[str]:
        if import_from.names is None or isinstance(import_from.names, cst.ImportStar):
            return []
        return [name.name.value for name in import_from.names if isinstance(name, cst.ImportAlias)]


def update_file(file_path: str) -> bool:
    """Update imports in a single file using LibCST"""
    try:
        path = Path(file_path)
        content = path.read_text()
        tree = cst.parse_module(content)

        transformer = ImportRewriter()
        new_tree = tree.visit(transformer)

        if transformer.imports_changed:
            path.write_text(new_tree.code)
            return True
        return False
    except Exception as e:
        logging.exception(f"  ❌ Error updating {file_path}: {e}")
        return False


def remove_shims_from_init():
    """Remove shimmed model imports from posthog/models/__init__.py"""
    init_file = Path("posthog/models/__init__.py")
    if not init_file.exists():
        logging.warning("posthog/models/__init__.py not found")
        return False

    try:
        content = init_file.read_text()
        tree = cst.parse_module(content)

        all_shimmed_models = set(SHIM_MAPPINGS.keys())
        transformer = ShimRemover(all_shimmed_models)
        new_tree = tree.visit(transformer)

        if transformer.removals_made:
            init_file.write_text(new_tree.code)
            logging.info("  ✅ Updated posthog/models/__init__.py")
            return True
        return False
    except Exception as e:
        logging.exception(f"  ❌ Error updating posthog/models/__init__.py: {e}")
        return False


def main():
    """Main execution combining ripgrep + LibCST"""
    logging.info("🚀 Unified shim removal (ripgrep + LibCST)...")

    # Use ripgrep to find files (fast!)
    logging.info("🔍 Finding files with posthog.models imports...")
    files = find_files_with_ripgrep()

    if not files:
        logging.info("No files found with posthog.models imports")
        return

    logging.info(f"📁 Found {len(files)} files to process")

    # Use LibCST to transform each file (safe!)
    updated_count = 0
    for file_path in files:
        if "posthog/models/__init__.py" in file_path:
            continue  # Handle separately

        logging.info(f"📝 Processing {file_path}")
        if update_file(file_path):
            updated_count += 1

    # Remove shims from main __init__.py
    logging.info("🧹 Removing shims from posthog/models/__init__.py")
    remove_shims_from_init()

    logging.info(f"✅ Complete! Updated {updated_count} files")


if __name__ == "__main__":
    main()
