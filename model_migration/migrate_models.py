#!/usr/bin/env python3
"""
Automated model migration script for moving PostHog models into product apps.
Uses LibCST for refactoring and intelligent migration editing.
"""

import os
import ast
import sys
import json
import logging
import subprocess
from pathlib import Path

import libcst as cst

logger = logging.getLogger(__name__)


class ImportTransformer(cst.CSTTransformer):
    """LibCST transformer to update import statements for moved models"""

    def __init__(self, model_names: set[str], target_app: str, module_name: str):
        self.model_names = model_names
        self.target_app = target_app
        self.module_name = module_name
        self.changed = False
        self.imports_to_add = []  # Store additional imports to add

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom | cst.RemovalSentinel | cst.FlattenSentinel:
        """Transform ImportFrom statements"""

        # Check if this is a posthog.models import
        if self._is_posthog_models_import(updated_node):
            return self._transform_posthog_models_import(updated_node)

        # Check if this is a direct module import like posthog.models.experiment
        if self._is_direct_module_import(updated_node):
            return self._transform_direct_module_import(updated_node)

        return updated_node

    def _is_posthog_models_import(self, node: cst.ImportFrom) -> bool:
        """Check if this is 'from posthog.models import ...'"""
        if not node.module:
            return False

        module_str = self._get_module_string(node.module)
        return module_str == "posthog.models"

    def _is_direct_module_import(self, node: cst.ImportFrom) -> bool:
        """Check if this is 'from posthog.models.experiment import ...' or 'from posthog.models.error_tracking import ...'"""
        if not node.module:
            return False

        module_str = self._get_module_string(node.module)

        # Handle both cases:
        # 1. Direct file: 'from posthog.models.experiment import ...' (module_name = "experiment")
        # 2. Subdirectory: 'from posthog.models.error_tracking import ...' (module_name = "error_tracking/error_tracking")
        # 3. Sub-module: 'from posthog.models.error_tracking.sql import ...' (module_name = "error_tracking/error_tracking")
        if "/" in self.module_name:
            # For subdirectory case, check against subdirectory name and sub-modules
            subdirectory_name = self.module_name.split("/")[0]
            return module_str == f"posthog.models.{subdirectory_name}" or module_str.startswith(
                f"posthog.models.{subdirectory_name}."
            )
        else:
            # For direct file case, check against module name
            return module_str == f"posthog.models.{self.module_name}"

    def _get_module_string(self, module: cst.CSTNode) -> str:
        """Convert module CST node to string"""
        if isinstance(module, cst.Name):
            return module.value
        elif isinstance(module, cst.Attribute):
            return f"{self._get_module_string(module.value)}.{module.attr.value}"
        else:
            # For other node types, generate the actual code
            return cst.Module(body=[cst.SimpleStatementLine(body=[cst.Expr(value=module)])]).code.strip()

    def _transform_posthog_models_import(self, node: cst.ImportFrom) -> cst.ImportFrom | cst.FlattenSentinel:
        """Transform 'from posthog.models import ...' statements"""
        if not node.names or isinstance(node.names, cst.ImportStar):
            return node

        # Extract import names
        current_imports = []
        for name in node.names:
            if isinstance(name, cst.ImportAlias):
                current_imports.append(name.name.value)

        # Separate moved models from remaining models
        remaining_imports = [name for name in current_imports if name not in self.model_names]
        moved_imports = [name for name in current_imports if name in self.model_names]

        if not moved_imports:
            return node  # No changes needed

        self.changed = True

        # Store the moved import to add later
        moved_module = cst.parse_expression(f"products.{self.target_app}.backend.models")
        moved_names = [cst.ImportAlias(name=cst.Name(name)) for name in moved_imports]
        moved_stmt = cst.ImportFrom(module=moved_module, names=moved_names)
        self.imports_to_add.append(moved_stmt)

        if remaining_imports:
            # Keep original import with remaining models only
            remaining_names = [cst.ImportAlias(name=cst.Name(name)) for name in remaining_imports]
            return node.with_changes(names=remaining_names)
        else:
            # Remove this import entirely (moved import will be added separately)
            return cst.RemovalSentinel.REMOVE

    def _transform_direct_module_import(self, node: cst.ImportFrom) -> cst.ImportFrom:
        """Transform 'from posthog.models.experiment import ...' statements"""
        self.changed = True

        module_str = self._get_module_string(node.module)

        # Handle sub-modules: preserve the sub-module part
        if "/" in self.module_name:
            subdirectory_name = self.module_name.split("/")[0]
            base_path = f"posthog.models.{subdirectory_name}"

            if module_str.startswith(base_path + "."):
                sub_module = module_str[len(base_path) :]  # Gets ".error_tracking", ".sql", or ".hogvm_stl"

                # Check if this is the main model file (same name as subdirectory)
                if sub_module == f".{subdirectory_name}":
                    # Main model file - goes to models.py
                    new_module_str = f"products.{self.target_app}.backend.models"
                else:
                    # Real sub-module like .sql or .hogvm_stl - preserve the name
                    new_module_str = f"products.{self.target_app}.backend{sub_module}"
            else:
                # Just the base subdirectory import
                new_module_str = f"products.{self.target_app}.backend.models"
        else:
            # Direct file case
            new_module_str = f"products.{self.target_app}.backend.models"

        new_module = cst.parse_expression(new_module_str)
        return node.with_changes(module=new_module)

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        """Add collected imports at the end of import section"""
        if not self.imports_to_add:
            return updated_node

        # Find the last import statement
        body = list(updated_node.body)
        last_import_idx = -1

        for i, stmt in enumerate(body):
            if isinstance(stmt, cst.SimpleStatementLine):
                for substmt in stmt.body:
                    if isinstance(substmt, cst.ImportFrom | cst.Import):
                        last_import_idx = i
                        break

        # Insert new imports after the last import
        if last_import_idx >= 0:
            for import_stmt in self.imports_to_add:
                last_import_idx += 1
                body.insert(last_import_idx, cst.SimpleStatementLine(body=[import_stmt]))

        return updated_node.with_changes(body=body)


class LLMLimitReachedError(Exception):
    """Raised when an AI provider reports that a usage limit has been reached."""


class LLMInvocationError(Exception):
    """Raised when invoking an AI provider fails for runtime reasons."""


class ModelMigrator:
    def __init__(
        self, config_file: str = "model_migration/migration_config.json", continue_from_migrations: bool = False
    ):
        self.root_dir = Path.cwd()
        self.continue_from_migrations = continue_from_migrations

        config_path = Path(config_file)
        if not config_path.is_absolute():
            config_path = self.root_dir / config_path
        self.config_path = config_path

        self._llm_limit_markers = [
            "rate limit",
            "limit reached",
            "out of credits",
            "usage limit",
            "quota",
        ]

        self.config = self.load_config()
        # Bowler doesn't need project initialization
        self._admin_classes_for_registration: list[tuple[str, str]] = []

    def load_config(self) -> dict:
        """Load migration configuration and normalize status flags."""
        if not self.config_path.exists():
            logger.error("❌ Configuration file not found: %s", self.config_path)
            sys.exit(1)

        with self.config_path.open() as f:
            config = json.load(f)

        modified = self._normalize_config(config)
        if modified:
            self.save_config(config)

        return config

    def save_config(self, config: dict | None = None) -> None:
        """Persist the migration configuration to disk."""
        if config is None:
            config = self.config

        with self.config_path.open("w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")

        self.config = config

    def _normalize_config(self, config: dict) -> bool:
        """Ensure every migration has a simple status flag."""
        modified = False
        migrations = config.setdefault("migrations", [])

        for migration in migrations:
            status_raw = migration.get("status", "todo")
            status = status_raw.lower() if isinstance(status_raw, str) else "todo"

            if status == "in_progress":
                status = "todo"

            if status not in {"todo", "done", "skip"}:
                status = "todo"

            if migration.get("status") != status:
                migration["status"] = status
                modified = True

        return modified

    def _pending_migrations(self) -> list[tuple[int, dict]]:
        """Return index/spec pairs for migrations still marked as todo."""
        pending = []
        for index, migration in enumerate(self.config.get("migrations", [])):
            if migration.get("status", "todo") == "todo":
                pending.append((index, migration))
        return pending

    def _ensure_model_db_tables(self, models_path: Path) -> None:
        """Ensure moved models keep referencing the original database tables."""
        try:
            source = models_path.read_text()
        except FileNotFoundError:
            return

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            logger.warning("⚠️  Failed to parse %s for db_table injection: %s", models_path, exc)
            return

        lines = source.splitlines()
        insertions: list[tuple[int, list[str]]] = []

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue

            class_name = node.name
            expected_table = f"posthog_{class_name.lower()}"

            # Only add Meta class to Django Model classes, not managers or other classes
            is_model_class = any(
                isinstance(base, ast.Name)
                and base.id.endswith("Model")
                or isinstance(base, ast.Attribute)
                and base.attr.endswith("Model")
                for base in node.bases
            )
            if not is_model_class:
                continue

            meta_class = next(
                (stmt for stmt in node.body if isinstance(stmt, ast.ClassDef) and stmt.name == "Meta"),
                None,
            )

            if meta_class:
                has_db_table = False
                for stmt in meta_class.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name) and target.id == "db_table":
                                has_db_table = True
                                break
                    elif isinstance(stmt, ast.AnnAssign):
                        target = stmt.target
                        if isinstance(target, ast.Name) and target.id == "db_table":
                            has_db_table = True
                    if has_db_table:
                        break

                if has_db_table:
                    continue

                if meta_class.body:
                    indent_line = lines[meta_class.body[0].lineno - 1]
                    indent = indent_line[: len(indent_line) - len(indent_line.lstrip())]
                    insert_after = meta_class.body[-1].end_lineno
                else:
                    meta_line = lines[meta_class.lineno - 1]
                    meta_indent = meta_line[: len(meta_line) - len(meta_line.lstrip())]
                    indent = meta_indent + "    "
                    insert_after = meta_class.lineno

                insertions.append((insert_after, [f'{indent}db_table = "{expected_table}"']))
            else:
                class_line = lines[node.lineno - 1]
                class_indent = class_line[: len(class_line) - len(class_line.lstrip())]
                body_indent = class_indent + "    "

                # Place Meta class after all fields but before methods
                insert_after = node.lineno
                if node.body:
                    # Find the last field assignment (before any method definitions)
                    last_field_line = node.lineno
                    for stmt in node.body:
                        if isinstance(stmt, ast.Assign) or isinstance(stmt, ast.AnnAssign):
                            last_field_line = stmt.end_lineno
                        elif isinstance(stmt, ast.FunctionDef):
                            break  # Stop at first method
                    insert_after = last_field_line

                insert_block = [
                    "",
                    f"{body_indent}class Meta:",
                    f'{body_indent}    db_table = "{expected_table}"',
                ]
                insertions.append((insert_after, insert_block))

        if not insertions:
            return

        for insert_after, block in sorted(insertions, key=lambda item: item[0], reverse=True):
            index = insert_after
            lines[index:index] = block

        models_path.write_text("\n".join(lines) + "\n")

    def run_command(self, cmd: str, description: str = "") -> tuple[bool, str]:
        """Run a shell command and return success status and output"""
        if description:
            logger.info("🔧 %s", description)

        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
            return True, result.stdout
        except subprocess.CalledProcessError:
            logger.exception("❌ Command failed: %s", cmd)
            return False, "Command failed"

    def _call_llm_cli(self, tool: str, prompt: str, file_content: str) -> str:
        """Invoke an AI CLI tool and return its stdout."""
        if tool == "claude":
            command = ["claude", "-p", prompt]
        elif tool == "codex":
            command = ["codex", "exec", prompt]
        else:
            raise ValueError(f"Unsupported LLM tool: {tool}")

        result = subprocess.run(
            command,
            input=file_content,
            capture_output=True,
            text=True,
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        combined_output = "\n".join(part for part in [stdout, stderr] if part).strip()

        if any(marker in combined_output.lower() for marker in self._llm_limit_markers):
            raise LLMLimitReachedError(combined_output or "Usage limit reached")

        if result.returncode != 0:
            raise LLMInvocationError(combined_output or f"{tool} invocation failed")

        return stdout

    def _extract_updated_content(self, llm_output: str) -> str:
        """Pull the updated file contents out of a fenced code block, if present."""
        import re

        code_block_match = re.search(r"```(?:python)?\n(.*?)\n```", llm_output, flags=re.DOTALL)
        if code_block_match:
            return code_block_match.group(1)
        return llm_output

    def _apply_llm_edit(self, file_path: Path, prompt: str) -> bool:
        """Apply an edit to a file using Claude with Codex fallback."""

        if not file_path.exists():
            logger.warning("⚠️  File not found for AI edit: %s", file_path)
            return False

        original_content = file_path.read_text()

        prompt_with_instructions = (
            f"{prompt}\n\n"
            "Respond with only the full updated file contents inside a single fenced code block labelled python (```python ... ```), with no other commentary."
        )

        used_tool = "Claude"

        logger.info("🤖 Invoking %s for AI-assisted edit on %s", used_tool, file_path)

        try:
            raw_output = self._call_llm_cli("claude", prompt_with_instructions, original_content)
        except LLMLimitReachedError as limit_error:
            logger.warning("⚠️  Claude limit reached (%s); attempting Codex fallback...", limit_error)
            try:
                raw_output = self._call_llm_cli("codex", prompt_with_instructions, original_content)
                used_tool = "Codex"
            except LLMLimitReachedError as codex_limit:
                logger.warning("⚠️  Codex also reported a limit: %s", codex_limit)
                return False
            except LLMInvocationError as codex_error:
                logger.warning("⚠️  Codex invocation failed: %s", codex_error)
                return False
        except LLMInvocationError as error:
            logger.warning("⚠️  Claude invocation failed: %s", error)
            return False

        updated_content = self._extract_updated_content(raw_output).rstrip()

        if not updated_content:
            logger.warning("⚠️  AI response did not contain updated content")
            return False

        file_path.write_text(updated_content + "\n")
        logger.info("✅ Applied AI edit with %s on %s", used_tool, file_path)
        return True

    def create_backend_structure(self, app_name: str) -> bool:
        """Create backend directory structure for product app"""
        products_dir = self.root_dir / "products"
        app_dir = products_dir / app_name
        backend_dir = app_dir / "backend"

        # Ensure products/__init__.py exists (needed for pytest discovery)
        products_init = products_dir / "__init__.py"
        if not products_init.exists():
            logger.info("📁 Creating products/__init__.py (needed for pytest)")
            products_init.touch()

        # Ensure product app __init__.py exists (needed for imports)
        app_init = app_dir / "__init__.py"
        if not app_init.exists():
            logger.info("📁 Creating %s/__init__.py (needed for imports)", app_name)
            app_init.touch()

        if not backend_dir.exists():
            logger.info("📁 Creating backend directory: %s", backend_dir)
            backend_dir.mkdir(parents=True, exist_ok=True)

            # Create __init__.py
            (backend_dir / "__init__.py").touch()

        return True

    def create_django_app_config(self, app_name: str, admin_registrations: list[tuple[str, str]] | None = None) -> bool:
        """Create Django app configuration in backend/"""
        app_dir = self.root_dir / "products" / app_name
        backend_dir = app_dir / "backend"

        # Check for old structure and warn (but not __init__.py which is needed)
        old_files_found = []

        old_apps_py = app_dir / "apps.py"
        if old_apps_py.exists():
            old_files_found.append(str(old_apps_py))

        old_models_py = app_dir / "models.py"
        if old_models_py.exists():
            old_files_found.append(str(old_models_py))

        if old_files_found:
            logger.warning("⚠️  WARNING: Found old product structure files that should be manually reviewed:")
            for file_path in old_files_found:
                logger.warning("⚠️    %s", file_path)
            logger.warning("⚠️  These files don't follow the new architecture (only backend/ should have Python files)")
            logger.warning("⚠️  Please review and remove them manually if they're not needed")

        # Create backend/apps.py
        apps_py = backend_dir / "apps.py"
        if not apps_py.exists():
            # Build AppConfig with optional admin registrations
            ready_method = ""
            if admin_registrations:
                ready_imports = (
                    "# TODO: Hacky\n        "
                    "_ = list(admin.site._registry)\n        "
                    "from django.contrib import admin\n        from .admin import (\n"
                )
                for _model_name, admin_class in admin_registrations:
                    ready_imports += f"            {admin_class},\n"
                ready_imports += "        )\n        from .models import (\n"
                for model_name, _admin_class in admin_registrations:
                    ready_imports += f"            {model_name},\n"
                ready_imports += "        )"

                ready_registrations = ""
                for model_name, admin_class in admin_registrations:
                    ready_registrations += f"        admin.site.register({model_name}, {admin_class})\n"

                ready_method = f"""
    def ready(self):
        # Import and register admin classes when Django is ready
        {ready_imports}

        # Register admin classes
{ready_registrations.rstrip()}"""

            app_config_content = f"""from django.apps import AppConfig


class {app_name.title()}Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.{app_name}.backend"
    label = "{app_name}"{ready_method}
"""
            with open(apps_py, "w") as f:
                f.write(app_config_content)
            logger.info("✅ Created Django app config: %s", apps_py)

        return True

    def move_admin_classes(self, model_names: set[str], target_app: str) -> bool:
        """Move Django admin classes to the product backend folder using new deduplication logic"""
        admin_admins_dir = self.root_dir / "posthog" / "admin" / "admins"
        backend_dir = self.root_dir / "products" / target_app / "backend"
        self._admin_classes_for_registration = []

        if not admin_admins_dir.exists():
            logger.warning("⚠️  Admin admins directory not found: %s", admin_admins_dir)
            return False

        # Find admin files that might be related to our models
        admin_files_to_move = []

        def to_snake_case(name: str) -> str:
            """Convert CamelCase to snake_case"""
            import re

            return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

        # Common naming patterns for admin files
        for model_name in model_names:
            snake_name = to_snake_case(model_name)
            potential_files = [
                f"{snake_name}_admin.py",
                f"{model_name.lower()}_admin.py",
                f"{model_name}_admin.py",
            ]
            for potential_file in potential_files:
                admin_file = admin_admins_dir / potential_file
                logger.debug("🔍 Checking admin file: %s (exists: %s)", admin_file, admin_file.exists())
                if admin_file.exists():
                    admin_files_to_move.append((admin_file, potential_file))
                    logger.debug("✅ Added admin file: %s", admin_file)

        # Also use glob pattern to catch any other related admin files
        import glob

        seen_filenames = {name for _, name in admin_files_to_move}

        for model_name in model_names:
            snake_name = to_snake_case(model_name)
            pattern = str(admin_admins_dir / f"*{snake_name}*admin*.py")
            for found_file in glob.glob(pattern):
                found_path = Path(found_file)
                logger.debug("🔍 Glob found admin file: %s (exists: %s)", found_path, found_path.exists())
                if found_path.exists() and found_path.name not in seen_filenames:
                    admin_files_to_move.append((found_path, found_path.name))
                    seen_filenames.add(found_path.name)
                    logger.debug("✅ Added glob admin file: %s", found_path)

        if not admin_files_to_move:
            logger.info("✅ No admin files found to move")
            return True

        # Use the new deduplication logic
        success = self._create_combined_admin_file(admin_files_to_move, backend_dir, model_names)
        if not success:
            return False

        # Create __init__.py in backend
        backend_init = backend_dir / "__init__.py"
        if not backend_init.exists():
            backend_init.touch()

        # Update admin __init__.py after move
        self._update_admin_init_after_move(admin_files_to_move, model_names, target_app)

        return True

    def _create_combined_admin_file(self, admin_files: list, target_dir, model_names: set[str]) -> bool:
        """Create combined admin.py file using simple approach like model combining"""
        try:
            admin_file = target_dir / "admin.py"
            combined_content = []
            seen_lines = set()

            # Header
            header = [
                "# Django admin classes for this product",
                "",
                "from django.contrib import admin",
                "",
                "from .models import (",
            ]
            for model_name in sorted(model_names):
                header.append(f"    {model_name},")
            header.extend([")", "", ""])
            combined_content.extend(header)

            # Process each admin file and extract only unique classes/functions
            seen_class_names = set()

            for admin_file_path, filename in admin_files:
                if not admin_file_path.exists():
                    logger.warning("⚠️  Skipping missing admin file: %s", admin_file_path)
                    continue

                with open(admin_file_path) as f:
                    content = f.read()

                combined_content.append(f"# === From {filename} ===")

                # Parse to find class definitions and avoid duplicates
                lines = content.split("\n")
                current_class = None
                class_lines = []

                for line in lines:
                    stripped = line.strip()

                    # Skip imports we'll replace
                    if stripped.startswith(("from posthog.models", "from django.contrib import admin")):
                        continue

                    # Detect class definitions
                    if stripped.startswith("class ") and "Admin(" in stripped:
                        # Extract class name
                        class_name = stripped.split("class ")[1].split("(")[0].strip()

                        if class_name in seen_class_names:
                            # Skip duplicate class - don't process until we find next class
                            current_class = "DUPLICATE"
                            continue
                        else:
                            # New unique class
                            seen_class_names.add(class_name)
                            current_class = class_name
                            class_lines = [line]

                    elif current_class == "DUPLICATE":
                        # Skip all lines of duplicate class until we hit next class or end
                        if not stripped.startswith(("def ", "class ")) or line.startswith("    "):
                            continue
                        else:
                            current_class = None  # End of duplicate class

                    elif current_class:
                        # We're inside a unique class - collect its lines
                        class_lines.append(line)

                        # End of class when we hit non-indented line (except empty lines)
                        if stripped and not line.startswith(("    ", "\t")) and not stripped.startswith(("def ", "@")):
                            # Add complete class
                            combined_content.extend(class_lines)
                            current_class = None
                            class_lines = []

                            # Process this line too (might be a function or another class)
                            if line not in seen_lines:
                                seen_lines.add(line)
                                combined_content.append(line)
                    else:
                        # Regular line outside classes - add if unique
                        if line and line not in seen_lines:
                            seen_lines.add(line)
                            combined_content.append(line)

                # Add any remaining class lines
                if current_class and current_class != "DUPLICATE":
                    combined_content.extend(class_lines)

                combined_content.append("")

                # Remove the old admin file
                admin_file_path.unlink()
                logger.info("🗑️  Removed old admin file: %s", admin_file_path)

            # Write combined file
            with open(admin_file, "w") as f:
                f.write("\n".join(combined_content))

            logger.info("✅ Created backend admin file: %s", admin_file)
            return True

        except Exception:
            logger.exception("❌ Failed to create combined admin file")
            return False

    def _update_admin_init_after_move(self, moved_files: list, model_names: set[str], target_app: str):
        """Update admin __init__.py after moving admin files"""
        admin_init = self.root_dir / "posthog" / "admin" / "__init__.py"

        try:
            with open(admin_init) as f:
                content = f.read()

            # Remove imports of moved admin classes
            import re

            # Find admin class imports that need to be removed
            for _admin_file, filename in moved_files:
                # Convert filename to likely admin class name
                admin_class_name = filename.replace(".py", "").replace("_", "").title() + "Admin"
                # Remove the import line
                content = re.sub(f"\\s*{admin_class_name},?\\n", "", content)

            # Remove model imports that were moved
            # Pattern to match the import block from posthog.models
            pattern = r"(from posthog\.models import \()(.*?)(\)\n)"
            match = re.search(pattern, content, re.DOTALL)

            if match:
                import_start, import_content, import_end = match.groups()

                # Filter out moved models
                import_lines = [line.strip().rstrip(",") for line in import_content.strip().split("\n") if line.strip()]
                remaining_imports = []

                for line in import_lines:
                    if not any(model_name in line for model_name in model_names):
                        remaining_imports.append(line)

                # Rebuild the import block
                new_posthog_imports = "from posthog.models import (\n"
                for imp in remaining_imports:
                    new_posthog_imports += f"    {imp},\n"
                new_posthog_imports += ")"

                content = content.replace(match.group(0), new_posthog_imports + "\n")

            # Remove admin.site.register calls for moved models
            for model_name in model_names:
                content = re.sub(f"\\s*admin\\.site\\.register\\({model_name}.*?\\)\\n", "", content)

            with open(admin_init, "w") as f:
                f.write(content)

            # Remove the old admin files
            for admin_file, _filename in moved_files:
                if admin_file.exists():
                    admin_file.unlink()
                    logger.info("🗑️  Removed old admin file: %s", admin_file)

            logger.info("✅ Updated admin __init__.py after moving admin classes")

        except Exception:
            logger.exception("❌ Failed to update admin __init__.py after move")

    def _extract_class_names_from_files(self, source_files: list[str]) -> set[str]:
        """Extract Django model class names from source files"""
        class_names = set()
        for source_file in source_files:
            source_path = self.root_dir / "posthog" / "models" / source_file
            if source_path.exists():
                try:
                    with open(source_path) as f:
                        content = f.read()
                    tree = ast.parse(content)
                    for node in tree.body:
                        if isinstance(node, ast.ClassDef):
                            class_names.add(node.name)
                except (FileNotFoundError, SyntaxError):
                    continue
        return class_names

    def _update_foreign_key_references(self, line: str, model_names: set[str]) -> str:
        """Update both string-based and direct foreign key references to include posthog. prefix"""
        import re

        # Only update references in ForeignKey, ManyToManyField, OneToOneField lines
        if not any(field_type in line for field_type in ["ForeignKey", "ManyToManyField", "OneToOneField"]):
            return line

        # First handle direct class references: ForeignKey(ClassName, ...) or ForeignKey(ClassName)
        # Pattern: field_type(ClassName, or field_type(ClassName)
        direct_pattern = r"\b(ForeignKey|ManyToManyField|OneToOneField)\(([A-Z][a-zA-Z]*)([\),])"

        def replace_direct(match):
            field_type = match.group(1)
            model_ref = match.group(2)
            delimiter = match.group(3)

            # Don't change if it's a model being moved
            if model_ref in model_names:
                return match.group(0)

            # Convert to string reference with posthog prefix
            return f'{field_type}("posthog.{model_ref}"{delimiter}'

        line = re.sub(direct_pattern, replace_direct, line)

        # Then handle existing string references (existing logic)
        # Pattern to match quoted model references in field definitions
        # Matches: "ModelName" but not "posthog.ModelName" (already prefixed)
        pattern = r'"([A-Z][a-zA-Z]*)"'

        def replace_reference(match):
            model_ref = match.group(1)
            # Don't prefix if it's one of our models being moved, or already has a prefix
            if model_ref in model_names or "." in model_ref:
                return match.group(0)  # Return unchanged
            # Add posthog. prefix for references to models staying in posthog
            return f'"posthog.{model_ref}"'

        return re.sub(pattern, replace_reference, line)

    def _update_external_references_to_moved_models(self, model_names: set[str], target_app: str) -> None:
        """Update references in external files to models we're moving"""
        import re

        # Files that commonly reference other models via ForeignKey strings
        external_files = [
            "posthog/models/tagged_item.py",
            "posthog/models/comment.py",
            "posthog/models/annotation.py",
            # Add more files as needed
        ]

        updated_files = 0
        for file_path in external_files:
            full_path = self.root_dir / file_path
            if not full_path.exists():
                continue

            try:
                content = full_path.read_text()
                original_content = content

                # Update ForeignKey references to moved models
                for model_name in model_names:
                    # Pattern for both single-line and multi-line ForeignKey definitions
                    # Handles: ForeignKey("ModelName") and ForeignKey(\n    "ModelName"
                    pattern = rf'(ForeignKey|ManyToManyField|OneToOneField)\s*\(\s*\n?\s*"{re.escape(model_name)}"'
                    replacement = rf'\1(\n        "{target_app}.{model_name}"'
                    content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

                if content != original_content:
                    full_path.write_text(content)
                    updated_files += 1
                    logger.info("📝 Updated external references in %s", file_path)

            except Exception as e:
                logger.warning("⚠️  Failed to update external references in %s: %s", file_path, e)

        if updated_files > 0:
            logger.info("✅ Updated external references in %d files", updated_files)

    def _expand_subdirectory_files(self, source_files: list[str]) -> tuple[list[str], list[str]]:
        """Expand subdirectory entries to include all Python files and identify non-model files"""
        expanded_files = []
        non_model_files = []

        for source_file in source_files:
            if "/" in source_file:
                # This is a subdirectory file - expand to include all files from the subdirectory
                subdirectory = source_file.split("/")[0]
                subdirectory_path = self.root_dir / "posthog" / "models" / subdirectory

                if subdirectory_path.exists() and subdirectory_path.is_dir():
                    logger.info("🔍 Expanding subdirectory: %s", subdirectory)

                    # Find all Python files in the subdirectory (recursively)
                    for py_file in subdirectory_path.rglob("*.py"):
                        if py_file.name == "__pycache__" or py_file.name == "__init__.py":
                            continue

                        # Calculate relative path from posthog/models/
                        relative_path = py_file.relative_to(self.root_dir / "posthog" / "models")
                        relative_str = str(relative_path)

                        expanded_files.append(relative_str)

                        # If it's not the main model file, it's a supporting file
                        if relative_str != source_file:
                            non_model_files.append(relative_str)

                    logger.info(
                        "📂 Found %d files in subdirectory %s",
                        len([f for f in expanded_files if f.startswith(subdirectory)]),
                        subdirectory,
                    )
                else:
                    # Just add the original file if subdirectory doesn't exist
                    expanded_files.append(source_file)
            else:
                # Regular file, add as-is
                expanded_files.append(source_file)

        return expanded_files, non_model_files

    def move_model_files_and_update_imports(self, source_files: list[str], target_app: str) -> bool:
        """Move files manually first, then use LibCST to update imports"""
        logger.info("🔄 Moving %d model files...", len(source_files))

        # Step 0: Expand any subdirectories to include all their files
        expanded_files, non_model_files = self._expand_subdirectory_files(source_files)
        logger.info("📁 Expanded to %d total files (%d supporting files)", len(expanded_files), len(non_model_files))

        target_dir = self.root_dir / "products" / target_app / "backend"
        target_models_py = target_dir / "models.py"

        # Step 1: Get model class names to avoid circular imports (only from original model files)
        model_names = self._extract_class_names_from_files(source_files)
        logger.info("📋 Model classes found: %s", list(model_names))

        # Step 2: Process model files (combine into models.py) and supporting files (copy individually)
        combined_content = []
        imports_seen = set()

        # First, process model files for combining
        for source_file in source_files:
            source_path = self.root_dir / "posthog" / "models" / source_file
            if not source_path.exists():
                logger.warning("⚠️  Source file not found: %s", source_path)
                continue

            logger.info("📄 Processing %s", source_file)

            with open(source_path) as f:
                content = f.read()

            # Parse file to separate imports from content properly
            lines = content.split("\n")
            file_imports = []
            file_content = []
            in_imports_section = True

            for line in lines:
                stripped = line.strip()

                # Determine if we're still in the imports section
                if in_imports_section:
                    if stripped.startswith(("from ", "import ")) and not stripped.startswith("#"):
                        # This is an import line - collect it
                        if stripped not in imports_seen and not any(
                            model_name in stripped for model_name in model_names
                        ):
                            file_imports.append(stripped)  # Always store without leading whitespace
                            imports_seen.add(stripped)
                    elif stripped == "" or stripped.startswith("#") or stripped == "if TYPE_CHECKING:":
                        # Skip empty lines, comments, and TYPE_CHECKING in import section
                        continue
                    else:
                        # First non-import line - we're done with imports section
                        in_imports_section = False
                        if stripped:  # Don't include empty line that ends imports
                            updated_line = self._update_foreign_key_references(line, model_names)
                            file_content.append(updated_line)
                else:
                    # We're in the content section - include everything except TYPE_CHECKING blocks
                    if stripped == "if TYPE_CHECKING:":
                        # Skip TYPE_CHECKING blocks but preserve other empty lines
                        continue
                    else:
                        # Keep all lines including empty ones to preserve formatting
                        updated_line = self._update_foreign_key_references(line, model_names)
                        file_content.append(updated_line)

            # Store the parsed content for later use
            combined_content.append(f"# === From {source_file} ===")
            combined_content.extend(file_imports)
            combined_content.extend(["", ""])
            combined_content.extend(file_content)
            combined_content.extend(["", ""])

        # Restructure to put all imports at the top
        final_content = []
        all_imports = sorted(imports_seen)  # Sort for consistency

        # Add all imports first
        final_content.extend(all_imports)
        final_content.extend(["", ""])  # Blank lines after imports

        # Add content sections (skip individual file imports)
        for i, line in enumerate(combined_content):
            if line.startswith("# === From "):
                # Add section header
                final_content.append(line)
                # Skip imports that follow, add only content
                j = i + 1
                while j < len(combined_content) and combined_content[j].strip():
                    if not combined_content[j].strip().startswith(("from ", "import ")):
                        break
                    j += 1
                # Add remaining content
                while j < len(combined_content):
                    if j + 1 < len(combined_content) and combined_content[j + 1].startswith("# === From "):
                        break
                    # Keep all lines including empty ones to preserve original formatting
                    final_content.append(combined_content[j])
                    j += 1
                final_content.extend(["", ""])

        # Write combined file
        with open(target_models_py, "w") as f:
            f.write("\n".join(final_content))

        self._ensure_model_db_tables(target_models_py)

        logger.info("✅ Created combined models.py: %s", target_models_py)

        # Step 2a: Copy supporting files (sql.py, hogvm_stl.py, test files, etc.)
        if non_model_files:
            logger.info("📁 Copying %d supporting files...", len(non_model_files))
            for support_file in non_model_files:
                source_path = self.root_dir / "posthog" / "models" / support_file

                # Preserve directory structure in backend/
                if "/" in support_file:
                    # Create subdirectories as needed (e.g., backend/test/)
                    target_file_path = target_dir / support_file.split("/", 1)[1]  # Remove first directory part
                else:
                    target_file_path = target_dir / support_file

                # Create parent directories if needed
                target_file_path.parent.mkdir(parents=True, exist_ok=True)

                # Move the file
                if source_path.exists():
                    import shutil

                    shutil.move(source_path, target_file_path)
                    logger.info("📄 Moved %s → %s", support_file, target_file_path.relative_to(self.root_dir))
                else:
                    logger.warning("⚠️  Supporting file not found: %s", source_path)

        # Step 3: Use libcst to update imports across the codebase
        logger.info("🔄 Using libcst to update imports across codebase...")
        for source_file in source_files:
            module_name = source_file.replace(".py", "")

            try:
                # Use libcst to find and replace imports
                self._update_imports_for_module(module_name, target_app)

            except Exception as e:
                logger.warning("⚠️  Error updating imports for %s: %s", module_name, e)
                # Continue anyway - we can check manually

        # Step 3: Remove original files
        for source_file in source_files:
            source_path = self.root_dir / "posthog" / "models" / source_file
            if source_path.exists():
                os.remove(source_path)
                logger.info("🗑️  Removed original: %s", source_path)

        return True

    def _update_imports_for_module(self, module_name: str, target_app: str):
        """Update imports for a specific module using libcst"""
        logger.info("🔄 Using libcst to update imports for %s...", module_name)

        # Get model class names that were moved from this module
        model_names = self._extract_class_names_from_files([f"{module_name}.py"])
        if not model_names:
            logger.warning("No model classes found for module %s", module_name)
            return True

        logger.info("Updating imports for models: %s", model_names)

        updated_files = 0

        # First, find files that actually contain imports we need to update
        logger.info("Finding files with relevant imports...")

        import subprocess

        # Handle both direct files and subdirectories for search patterns
        if "/" in module_name:
            # For subdirectory case, use just the subdirectory name for imports
            subdirectory_name = module_name.split("/")[0]
            search_module_name = subdirectory_name
        else:
            # For direct file case, use the module name
            search_module_name = module_name

        relevant_patterns = [
            f"posthog.models.{search_module_name}",  # Direct module imports
            "posthog.models import",  # General posthog.models imports
        ]
        # Add sub-module patterns for subdirectories
        if "/" in module_name:
            relevant_patterns.append(
                f"posthog.models.{search_module_name}\\."
            )  # Sub-module imports like .sql, .hogvm_stl

        candidate_files = set()
        for pattern in relevant_patterns:
            try:
                result = subprocess.run(
                    ["grep", "-r", "-l", "--include=*.py", pattern, str(self.root_dir)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    files = result.stdout.strip().split("\n")
                    candidate_files.update(Path(f) for f in files if f)
            except Exception as e:
                logger.warning("Failed to grep for pattern %s: %s", pattern, e)

        logger.info("Found %d candidate files to process", len(candidate_files))

        # Process only the candidate files
        for file_path in candidate_files:
            if not file_path.exists():
                continue

            try:
                # Read and parse file
                content = file_path.read_text(encoding="utf-8")
                tree = cst.parse_module(content)

                # Transform the tree
                transformer = ImportTransformer(model_names, target_app, module_name)
                new_tree = tree.visit(transformer)

                # Write back if changed
                if transformer.changed:
                    file_path.write_text(new_tree.code, encoding="utf-8")
                    updated_files += 1
                    logger.debug("Updated imports in %s", file_path)

            except Exception as e:
                logger.warning("Failed to process %s: %s", file_path, e)
                continue

        logger.info("✅ LibCST updated imports in %d files", updated_files)
        return True

    def update_posthog_models_init(self, source_files: list[str], target_app: str) -> bool:
        """Remove imports from posthog/models/__init__.py for moved models to prevent circular imports"""
        init_file = self.root_dir / "posthog" / "models" / "__init__.py"

        with open(init_file) as f:
            content = f.read()

        # For each moved model, remove the import line entirely
        for source_file in source_files:
            module_name = source_file.replace(".py", "")
            import re

            # Handle both direct files and subdirectories
            if "/" in source_file:
                # For subdirectory case like error_tracking/error_tracking.py
                subdirectory_name = source_file.split("/")[0]
                # Pattern for multiline imports: from .error_tracking import (\n    Class1,\n    Class2,\n)
                pattern = rf"from \.{re.escape(subdirectory_name)} import \([^)]*\)\n?"
                content = re.sub(pattern, "", content, flags=re.DOTALL)
                # Also handle single line imports: from .error_tracking import Class1, Class2
                pattern = rf"from \.{re.escape(subdirectory_name)} import .+\n"
                content = re.sub(pattern, "", content)
            else:
                # For direct file case: from .MODULE import Class1, Class2
                pattern = rf"from \.{re.escape(module_name)} import .+\n"
                content = re.sub(pattern, "", content)

        with open(init_file, "w") as f:
            f.write(content)

        logger.info("✅ Removed imports from posthog/models/__init__.py to prevent circular imports")
        return True

    def update_settings(self, target_app: str) -> bool:
        """Add the new app to Django settings"""
        settings_file = self.root_dir / "posthog" / "settings" / "web.py"

        with open(settings_file) as f:
            content = f.read()

        # Check if already added
        app_config_path = f'"products.{target_app}.backend.apps.{target_app.title().strip("_")}Config"'
        if app_config_path in content:
            logger.info("✅ App %s already in settings", target_app)
            return True

        # Add to PRODUCTS_APPS
        pattern = r"(PRODUCTS_APPS = \[)(.*?)(\])"

        def replacement(match):
            apps_content = match.group(2)
            # Add new app before the closing bracket
            return f"{match.group(1)}{apps_content}    {app_config_path.strip('_')},\n{match.group(3)}"

        new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

        if new_content != content:
            with open(settings_file, "w") as f:
                f.write(new_content)
            logger.info("✅ Added %s to PRODUCTS_APPS", target_app)

        return True

    def cleanup_old_model_directory(self, source_files: list[str], target_app: str) -> bool:
        """Delete old posthog/models/<app>/ directories after successful migration"""
        # Only cleanup if all source files are from a subdirectory
        subdirectories_to_delete = set()

        for source_file in source_files:
            if "/" in source_file:
                # Extract subdirectory name
                subdirectory = source_file.split("/")[0]
                subdirectories_to_delete.add(subdirectory)

        if not subdirectories_to_delete:
            logger.info("✅ No subdirectories to clean up")
            return True

        for subdirectory in subdirectories_to_delete:
            old_dir = self.root_dir / "posthog" / "models" / subdirectory

            if old_dir.exists() and old_dir.is_dir():
                import shutil

                shutil.rmtree(old_dir)
                logger.info("🗑️  Deleted old model directory: %s", old_dir)
            else:
                logger.warning("⚠️  Old model directory not found: %s", old_dir)

        return True

    def update_tach_config(self, target_app: str) -> bool:
        """Add product entry to tach.toml for dependency tracking"""
        tach_file = self.root_dir / "tach.toml"

        if not tach_file.exists():
            logger.warning("⚠️  tach.toml not found, skipping")
            return True

        try:
            content = tach_file.read_text()

            # Check if product already exists in tach.toml
            product_entry = f'path = "products.{target_app}"'
            if product_entry in content:
                logger.info("✅ Product %s already in tach.toml", target_app)
                return True

            # Find the last products module entry to insert after
            import re

            # Pattern to find all products.* module blocks
            product_pattern = r'\[\[modules\]\]\npath = "products\.[^"]+"\ndepends_on = \["posthog"\]'
            matches = list(re.finditer(product_pattern, content))

            if not matches:
                logger.warning("⚠️  No existing products modules found in tach.toml, cannot determine insertion point")
                return False

            # Find the position after the last products module
            last_match = matches[-1]
            insert_position = last_match.end()

            # Create new module entry
            new_entry = f'\n\n[[modules]]\npath = "products.{target_app}"\ndepends_on = ["posthog"]'

            # Insert the new entry
            new_content = content[:insert_position] + new_entry + content[insert_position:]

            tach_file.write_text(new_content)
            logger.info("✅ Added products.%s to tach.toml", target_app)

            # Also need to add to posthog's depends_on list
            posthog_pattern = r'(\[\[modules\]\]\npath = "posthog"\ndepends_on = \[)(.*?)(\])'

            def add_to_posthog_deps(match):
                prefix = match.group(1)
                deps_content = match.group(2)
                suffix = match.group(3)

                # Check if already in dependencies
                if f'"products.{target_app}"' in deps_content:
                    return match.group(0)

                # Add new dependency before the closing bracket
                # Find the line with the last product dependency
                lines = deps_content.split("\n")
                new_dep = f'    "products.{target_app}",'

                # Insert before the closing comment or at the end
                for i, line in enumerate(lines):
                    if line.strip().startswith("]"):
                        lines.insert(i, new_dep)
                        break
                else:
                    # Add at the end if no closing bracket found
                    lines.append(new_dep)

                return prefix + "\n".join(lines) + suffix

            new_content = re.sub(posthog_pattern, add_to_posthog_deps, new_content, flags=re.DOTALL)
            tach_file.write_text(new_content)
            logger.info("✅ Added products.%s to posthog dependencies in tach.toml", target_app)

            return True

        except Exception:
            logger.exception("❌ Failed to update tach.toml")
            return False

    def generate_migrations(self, target_app: str) -> tuple[bool, str, str]:
        """Generate Django migrations with proper naming"""
        logger.info("🔄 Generating migrations for %s...", target_app)

        # Generate with descriptive names as per README
        success, output = self.run_command(
            f"python manage.py makemigrations {target_app} -n migrate_{target_app}_models",
            f"Generating migration for {target_app}",
        )

        if not success:
            return False, "", ""

        # Also generate the posthog removal migration
        posthog_success, posthog_output = self.run_command(
            f"python manage.py makemigrations posthog -n remove_{target_app}_models",
            f"Generating removal migration for posthog",
        )

        if not posthog_success:
            return False, "", ""

        # Find generated migration files
        migration_dir = self.root_dir / "products" / target_app / "backend" / "migrations"
        posthog_migration_dir = self.root_dir / "posthog" / "migrations"

        # Find the newest migration files
        target_migration = ""
        posthog_migration = ""

        if migration_dir.exists():
            migrations = sorted([f for f in os.listdir(migration_dir) if f.endswith(".py") and f != "__init__.py"])
            if migrations:
                target_migration = str(migration_dir / migrations[-1])

        posthog_migrations: list[str] = []
        if posthog_migration_dir.exists():
            posthog_migrations = sorted(
                [f for f in os.listdir(posthog_migration_dir) if f.endswith(".py") and f != "__init__.py"]
            )
        if posthog_migrations:
            posthog_migration = str(posthog_migration_dir / posthog_migrations[-1])

        return True, target_migration, posthog_migration

    def edit_migrations_with_claude(self, target_migration: str, posthog_migration: str) -> bool:
        """Use Claude Code CLI to intelligently edit migrations"""
        logger.info("🤖 Using Claude Code to edit migrations...")

        edits_succeeded = True

        if target_migration:
            target_prompt = (
                "Please edit the Django migration at {path} to follow the exact proven pattern from "
                "products/batch_exports/migrations/0001_initial.py. Make the migration look structurally identical to that file, "
                "with only model names and fields differing:\n\n"
                "1. Wrap ALL operations in a single migrations.SeparateDatabaseAndState block.\n"
                "   - Do not leave any operations at the top level.\n\n"
                "2. Place every schema/state operation (CreateModel, AddConstraint, AddField, AlterField, etc.) "
                "inside the state_operations list.\n\n"
                "3. The database_operations list must contain exactly one element: the comment "
                "'# No database operations - table already exists with this name'. "
                "Do not add any RunSQL, RunPython, or other operations.\n\n"
                "4. Preserve the existing db_table configuration so the model continues using the original table.\n\n"
                "5. Do NOT set managed=False. Keep the model fully managed (managed=True is implicit).\n\n"
                "6. Do NOT introduce any changes not present in the original migration (dependencies, imports, or extra operations).\n\n"
                "In summary: the final migration must mirror products/batch_exports/migrations/0001_initial.py in structure, "
                "with only the model definitions differing."
            ).format(path=target_migration)

            if not self._apply_llm_edit(Path(target_migration), target_prompt):
                logger.warning("⚠️  Automated edit for target migration failed; manual review needed")
                edits_succeeded = False

        if posthog_migration:
            posthog_prompt = (
                "You are given a Django migration file at {path}. Edit it EXACTLY as follows:\n\n"
                "1. At the top of the file, immediately after the imports, insert ONE helper function:\n"
                "   def update_content_type(apps, schema_editor):\n"
                "       ContentType = apps.get_model('contenttypes', 'ContentType')\n"
                "       for model in ['<modelname1>', '<modelname2>', '<modelname3>']:\n"
                "           try:\n"
                "               ct = ContentType.objects.get(app_label='posthog', model=model)\n"
                "               ct.app_label = '<target_app>'\n"
                "               ct.save()\n"
                "           except ContentType.DoesNotExist:\n"
                "               pass\n\n"
                "   def reverse_content_type(apps, schema_editor):\n"
                "       ContentType = apps.get_model('contenttypes', 'ContentType')\n"
                "       for model in ['<modelname1>', '<modelname2>', '<modelname3>']:\n"
                "           try:\n"
                "               ct = ContentType.objects.get(app_label='<target_app>', model=model)\n"
                "               ct.app_label = 'posthog'\n"
                "               ct.save()\n"
                "           except ContentType.DoesNotExist:\n"
                "               pass\n\n"
                "   - Replace <modelname1>, <modelname2>, etc. with ALL the lowercase model names being deleted in this migration.\n"
                "   - Replace <target_app> with the lowercase app label of the new app (e.g. 'experiments').\n"
                "   - There must be exactly one update_content_type function and one reverse_content_type function.\n\n"
                "2. No model should actually be deleted in this migration:\n"
                "   - Wrap ALL operations in a single migrations.SeparateDatabaseAndState block.\n"
                "   - Place RunPython(update_content_type, reverse_content_type) ONLY in database_operations.\n"
                "   - Do NOT drop any database tables or columns.\n\n"
                "3. Do not duplicate update_content_type. It must be defined once and referenced in SeparateDatabaseAndState.\n\n"
                "4. The final migration must:\n"
                "   - Delete and alter any fields and the models in state only (so Django no longer tracks them under 'posthog').\n"
                "   - Keep the underlying database tables intact.\n"
                "   - Update django_content_type rows so they point to the new app label.\n\n"
                "5. Do not make ANY other changes. Keep dependencies, imports, and class Migration exactly as they are except for the required edits above.\n"
            ).format(path=posthog_migration)

            if not self._apply_llm_edit(Path(posthog_migration), posthog_prompt):
                logger.warning("⚠️  Automated edit for posthog migration failed; manual review needed")
                edits_succeeded = False

        return edits_succeeded

    def run_tests(self, target_app: str) -> bool:
        """Run tests to verify the migration worked"""
        logger.info("🧪 Running tests for %s...", target_app)

        # Test importing models
        success, _ = self.run_command(
            f'python manage.py shell -c "from products.{target_app}.backend.models import *; print(\\"✅ Models import successfully\\")"',
            "Testing model imports",
        )

        if not success:
            return False

        # Test migration plan
        success, output = self.run_command("python manage.py migrate --plan", "Checking migration plan")

        return success

    def _extract_models_from_content(self, content: str) -> set[str]:
        """Extract Django model class names from file content"""
        import ast

        model_names = set()

        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if this is likely a Django model
                    for base in node.bases:
                        if (
                            isinstance(base, ast.Attribute)
                            and isinstance(base.value, ast.Name)
                            and base.value.id == "models"
                            and base.attr == "Model"
                        ):
                            model_names.add(node.name)
                        elif isinstance(base, ast.Name) and base.id in ["Model", "AbstractBaseUser", "AbstractUser"]:
                            model_names.add(node.name)
        except SyntaxError:
            logger.warning("⚠️  Syntax error parsing content, skipping model extraction")

        return model_names

    def migrate_models(self, migration_spec: dict) -> bool:
        """Execute a single model migration with optimized processing"""
        name = migration_spec["name"]
        source_files = migration_spec["source_files"]
        target_app = migration_spec["target_app"]
        create_backend = migration_spec.get("create_backend_dir", False)

        logger.info("\n🚀 Starting migration: %s", name)
        logger.info("   Source files: %s", source_files)
        logger.info("   Target app: %s", target_app)

        if self.continue_from_migrations:
            logger.info("🔄 Continuing from migrations step (skipping file operations)")
            # Extract model class names from the target backend models.py file
            target_models_file = self.root_dir / "products" / target_app / "backend" / "models.py"
            if not target_models_file.exists():
                logger.error("❌ Cannot continue: target models.py not found at %s", target_models_file)
                return False

            # Ensure db_table declarations are present even in continue mode
            self._ensure_model_db_tables(target_models_file)

            with open(target_models_file) as f:
                content = f.read()
            model_names = self._extract_models_from_content(content)
            logger.info("📋 Model classes found in target: %s", list(model_names))
        else:
            # Step 1: Create backend structure if needed
            if create_backend:
                if not self.create_backend_structure(target_app):
                    return False

            # Step 2: Extract model class names early (before files are moved/deleted)
            model_names = self._extract_class_names_from_files(source_files)
            logger.info("📋 Model classes found: %s", list(model_names))

            # Step 3: Update posthog/models/__init__.py imports (before LibCST to prevent circular imports)
            if not self.update_posthog_models_init(source_files, target_app):
                return False

            # Step 4: Move model files and update imports with LibCST
            if not self.move_model_files_and_update_imports(source_files, target_app):
                return False

            # Step 5: Update external file references to moved models
            self._update_external_references_to_moved_models(model_names, target_app)

            # Step 6: Move Django admin classes to product backend
            if not self.move_admin_classes(model_names, target_app):
                logger.warning("⚠️  Admin class migration failed, but continuing...")

            admin_registrations = getattr(self, "_admin_classes_for_registration", [])

            # Step 7: Create Django app configuration (register admin classes when available)
            if not self.create_django_app_config(target_app, admin_registrations):
                return False

            # Step 8: Update settings
            if not self.update_settings(target_app):
                return False

            proceed = input(
                "\n🔍 Please review the changes so far. "
                "Also run `python manage.py migrate --plan` to verify there are no errors. "
                "If everything looks good, type 'yes' to proceed with migrations, "
                "or 'quit' to exit (you can resume later with --continue flag): "
            )
            if proceed.strip().lower() == "quit":
                logger.info("🛑 Migration paused by user. Resume with --continue flag.")
                return False
            elif proceed.strip().lower() != "yes":
                logger.info("🛑 Migration aborted by user.")
                return False

        # Step 9: Generate migrations
        success, target_migration, posthog_migration = self.generate_migrations(target_app)
        if not success:
            return False

        # Step 10: Edit migrations with Claude
        if not self.edit_migrations_with_claude(target_migration, posthog_migration):
            return False

        # Step 11: Test
        if not self.run_tests(target_app):
            return False

        # Step 12: Cleanup old model directories
        if not self.cleanup_old_model_directory(source_files, target_app):
            logger.warning("⚠️  Cleanup of old model directory failed, but continuing...")

        # Step 13: Update tach.toml
        if not self.update_tach_config(target_app):
            logger.warning("⚠️  Failed to update tach.toml, but continuing...")

        logger.info("✅ Migration %s completed successfully!", name)
        return True

    def run_all_migrations(self, single_mode: bool = False):
        """Run migrations based on their status flags."""
        mode_label = "single" if single_mode else "batch"
        logger.info("🎯 Starting %s migration run...\n", mode_label)

        pending = self._pending_migrations()
        if not pending:
            logger.info(
                "✅ No migrations marked as todo. Update migration_config.json if you want to schedule more work."
            )
            return

        if single_mode:
            pending = pending[:1]

        successful = 0
        total = len(pending)

        for position, (index, migration_spec) in enumerate(pending, start=1):
            name = migration_spec.get("name", f"migration_{index}")
            banner = "=" * 60
            logger.info("\n%s", banner)
            logger.info("🚀 Migration %d/%d: %s", position, total, name)
            logger.info("%s", banner)

            if self.migrate_models(migration_spec):
                successful += 1
                self.config["migrations"][index]["status"] = "done"
                self.save_config()
                logger.info("✅ Migration %s completed successfully and marked as done in %s", name, self.config_path)

                if single_mode:
                    logger.info("\n🛑 Single mode: Stopping after first completed migration.")
                    break
            else:
                logger.error("❌ Migration %s failed. Status remains todo.", name)
                break

        logger.info("\n📊 Results: %d/%d migrations completed in this run", successful, total)

        if successful == total:
            if single_mode:
                logger.info("🔍 Single migration run finished. Review the diff before scheduling the next item.")
            else:
                logger.info(
                    "🎉 All pending migrations completed! Consider running 'python manage.py migrate --plan' to verify."
                )
        else:
            logger.warning("⚠️  Stopping early due to a failure or manual interruption.")


if __name__ == "__main__":
    import re
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Check for command line flags
    single_mode = "--single" in sys.argv
    continue_mode = "--continue" in sys.argv

    if continue_mode and single_mode:
        logger.info("🔄 Running in single continue mode")
    elif continue_mode:
        logger.info("🔄 Running in continue mode (from migrations step)")
    elif single_mode:
        logger.info("🎯 Running in single mode")

    migrator = ModelMigrator(continue_from_migrations=continue_mode)
    migrator.run_all_migrations(single_mode=single_mode)
