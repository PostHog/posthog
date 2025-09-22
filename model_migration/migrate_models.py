#!/usr/bin/env python3
"""
Automated model migration script for moving PostHog models into product apps.
Uses rope for refactoring and Claude Code CLI for intelligent migration editing.
"""

import os
import ast
import json
import logging
import subprocess
from pathlib import Path

import rope.base.project
import rope.refactor.move
import rope.base.resources

logger = logging.getLogger(__name__)


class LLMLimitReachedError(Exception):
    """Raised when an AI provider reports that a usage limit has been reached."""


class LLMInvocationError(Exception):
    """Raised when invoking an AI provider fails for runtime reasons."""


class ModelMigrator:
    def __init__(self, config_file: str = "model_migration/migration_config.json"):
        self.root_dir = Path.cwd()

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
        self.rope_project = rope.base.project.Project(str(self.root_dir))

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

                insert_after = node.lineno
                if node.body:
                    first_stmt = node.body[0]
                    if (
                        isinstance(first_stmt, ast.Expr)
                        and isinstance(first_stmt.value, ast.Constant)
                        and isinstance(first_stmt.value.value, str)
                    ):
                        insert_after = first_stmt.end_lineno

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
        except subprocess.CalledProcessError as e:
            logging.exception("❌ Command failed: %s", cmd)
            return False, e.stderr

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
        backend_dir = self.root_dir / "products" / app_name / "backend"

        if not backend_dir.exists():
            logger.info("📁 Creating backend directory: %s", backend_dir)
            backend_dir.mkdir(parents=True, exist_ok=True)

            # Create __init__.py
            (backend_dir / "__init__.py").touch()

        return True

    def create_django_app_config(self, app_name: str) -> bool:
        """Create Django app configuration"""
        app_dir = self.root_dir / "products" / app_name
        apps_py = app_dir / "apps.py"

        if not apps_py.exists():
            app_config_content = f"""from django.apps import AppConfig


class {app_name.title()}Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.{app_name}"
    label = "{app_name}"
"""
            with open(apps_py, "w") as f:
                f.write(app_config_content)
            logger.info("✅ Created Django app config: %s", apps_py)

        # Create proxy models.py
        models_py = app_dir / "models.py"
        if not models_py.exists():
            models_content = "# Import models from backend to make them discoverable by Django\nfrom .backend.models import *  # noqa: F403, F401\n"
            with open(models_py, "w") as f:
                f.write(models_content)
            logger.info("✅ Created proxy models.py: %s", models_py)

        return True

    def move_model_files_manually_then_rope(self, source_files: list[str], target_app: str) -> bool:
        """Move files manually first, then use rope to update imports"""
        logger.info("🔄 Moving %d model files...", len(source_files))

        target_dir = self.root_dir / "products" / target_app / "backend"
        target_models_py = target_dir / "models.py"

        # Step 1: Manually move and combine files
        combined_content = []
        imports_seen = set()

        for source_file in source_files:
            source_path = self.root_dir / "posthog" / "models" / source_file
            if not source_path.exists():
                logger.warning("⚠️  Source file not found: %s", source_path)
                continue

            logger.info("📄 Processing %s", source_file)

            with open(source_path) as f:
                content = f.read()

            # Extract imports and content
            lines = content.split("\n")
            file_imports = []
            file_content = []

            for line in lines:
                if line.strip().startswith(("from ", "import ")) and not line.strip().startswith("#"):
                    if line not in imports_seen:
                        file_imports.append(line)
                        imports_seen.add(line)
                else:
                    file_content.append(line)

            combined_content.extend(file_imports)
            combined_content.extend(["", ""])
            combined_content.extend(file_content)
            combined_content.extend(["", ""])

        # Write combined file
        with open(target_models_py, "w") as f:
            f.write("\n".join(combined_content))

        self._ensure_model_db_tables(target_models_py)

        logger.info("✅ Created combined models.py: %s", target_models_py)

        # Step 2: Use rope to update imports across the codebase
        logger.info("🔄 Using rope to update imports across codebase...")
        for source_file in source_files:
            module_name = source_file.replace(".py", "")

            try:
                # Use rope to find and replace imports

                # This is simpler - just update the imports
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
        """Update imports for a specific module using simple string replacement"""
        import re

        # Find all Python files and update imports
        updated_files = 0

        for root, dirs, files in os.walk(str(self.root_dir)):
            # Skip some directories
            dirs[:] = [d for d in dirs if d not in ["__pycache__", ".git", "node_modules"]]

            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path) as f:
                            content = f.read()

                        original_content = content

                        # Update various import patterns
                        patterns = [
                            (
                                rf"from posthog\.models\.{re.escape(module_name)} import (.+)",
                                rf"from products.{target_app}.backend.models import \1",
                            ),
                            (
                                rf"import posthog\.models\.{re.escape(module_name)}",
                                rf"import products.{target_app}.backend.models",
                            ),
                            (
                                rf"posthog\.models\.{re.escape(module_name)}\.",
                                rf"products.{target_app}.backend.models.",
                            ),
                        ]

                        for pattern, replacement in patterns:
                            content = re.sub(pattern, replacement, content)

                        if content != original_content:
                            with open(file_path, "w") as f:
                                f.write(content)
                            updated_files += 1

                    except Exception:
                        # Skip files that can't be read/written
                        pass

        logger.info("✅ Updated imports in %d files", updated_files)
        return True

    def _combine_model_files(self, source_files: list[str], target_app: str) -> bool:
        """Combine multiple model files into one models.py"""
        target_dir = self.root_dir / "products" / target_app / "backend"
        target_models_py = target_dir / "models.py"

        logger.info("🔗 Combining %d files into models.py", len(source_files))

        combined_content = []
        imports_seen = set()

        for source_file in source_files:
            moved_file = target_dir / source_file
            if not moved_file.exists():
                continue

            with open(moved_file) as f:
                content = f.read()

            # Parse and combine content intelligently
            lines = content.split("\n")
            file_imports = []
            file_content = []

            for line in lines:
                if line.strip().startswith(("from ", "import ")) and not line.strip().startswith("#"):
                    if line not in imports_seen:
                        file_imports.append(line)
                        imports_seen.add(line)
                else:
                    file_content.append(line)

            combined_content.extend(file_imports)
            combined_content.extend(["", ""])
            combined_content.extend(file_content)
            combined_content.extend(["", ""])

            # Remove the individual file
            os.remove(moved_file)

        # Write combined file
        with open(target_models_py, "w") as f:
            f.write("\n".join(combined_content))

        logger.info("✅ Created combined models.py: %s", target_models_py)
        return True

    def update_posthog_models_init(self, source_files: list[str], target_app: str) -> bool:
        """Update posthog/models/__init__.py to import from new location"""
        init_file = self.root_dir / "posthog" / "models" / "__init__.py"

        with open(init_file) as f:
            content = f.read()

        # For each moved model, update the import in __init__.py
        for source_file in source_files:
            module_name = source_file.replace(".py", "")

            # Find imports from the old location and replace them
            import re

            # Pattern: from .MODULE import Class1, Class2
            pattern = rf"from \.{re.escape(module_name)} import (.+)"
            replacement = rf"from products.{target_app}.backend.models import \1"
            content = re.sub(pattern, replacement, content)

        with open(init_file, "w") as f:
            f.write(content)

        logger.info("✅ Updated posthog/models/__init__.py imports")
        return True

    def update_settings(self, target_app: str) -> bool:
        """Add the new app to Django settings"""
        settings_file = self.root_dir / "posthog" / "settings" / "web.py"

        with open(settings_file) as f:
            content = f.read()

        # Check if already added
        if f'"products.{target_app}"' in content:
            logger.info("✅ App %s already in settings", target_app)
            return True

        # Add to PRODUCTS_APPS
        pattern = r"(PRODUCTS_APPS = \[)(.*?)(\])"

        def replacement(match):
            apps_content = match.group(2)
            # Add new app before the closing bracket
            return f'{match.group(1)}{apps_content}    "products.{target_app}",\n{match.group(3)}'

        new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

        if new_content != content:
            with open(settings_file, "w") as f:
                f.write(new_content)
            logger.info("✅ Added %s to PRODUCTS_APPS", target_app)

        return True

    def generate_migrations(self, target_app: str) -> tuple[bool, str, str]:
        """Generate Django migrations with proper naming"""
        logger.info("🔄 Generating migrations for %s...", target_app)

        # Generate with descriptive names as per README
        success, output = self.run_command(
            f"python manage.py makemigrations {target_app} -n initial_migration",
            f"Generating initial migration for {target_app}",
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
        migration_dir = self.root_dir / "products" / target_app / "migrations"
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
                "Please edit the Django migration at {path} to follow the proven pattern from "
                "products/batch_exports/migrations/0001_initial.py:\n\n"
                "1. Wrap the entire set of operations in migrations.SeparateDatabaseAndState\n"
                "2. Place every schema/state operation (CreateModel, AddConstraint, AddField, etc.) inside the state_operations list so nothing remains at the top level\n"
                "3. Leave database_operations as an empty list containing only the comment '# No database operations - table already exists with this name'\n"
                "4. Keep the existing db_table configuration\n"
                "5. Do NOT add managed=False - keep the model normally managed"
            ).format(path=target_migration)

            if not self._apply_llm_edit(Path(target_migration), target_prompt):
                logger.warning("⚠️  Automated edit for target migration failed; manual review needed")
                edits_succeeded = False

        if posthog_migration:
            posthog_prompt = (
                "Please edit the Django migration at {path} as follows:\n\n"
                "1. Introduce an update_content_type helper exactly as shown below and insert it near the top of the file:\n"
                "   def update_content_type(apps, schema_editor):\n"
                '       ContentType = apps.get_model("contenttypes", "ContentType")\n'
                "       try:\n"
                '           content_type = ContentType.objects.get(app_label="posthog", model="<modelname>")\n'
                '           content_type.app_label = "<target_app>"\n'
                "           content_type.save()\n"
                "       except ContentType.DoesNotExist:\n"
                "           pass\n\n"
                "2. Wrap the DeleteModel in SeparateDatabaseAndState placing DeleteModel in state_operations and"
                " RunPython(update_content_type) in database_operations\n"
                "3. Replace <modelname> and <target_app> with the correct values for this migration"
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

    def migrate_models(self, migration_spec: dict) -> bool:
        """Execute a single model migration"""
        name = migration_spec["name"]
        source_files = migration_spec["source_files"]
        target_app = migration_spec["target_app"]
        create_backend = migration_spec.get("create_backend_dir", False)

        logger.info("\n🚀 Starting migration: %s", name)
        logger.info("   Source files: %s", source_files)
        logger.info("   Target app: %s", target_app)

        # Step 1: Create backend structure if needed
        if create_backend:
            if not self.create_backend_structure(target_app):
                return False

        # Step 2: Create Django app configuration
        if not self.create_django_app_config(target_app):
            return False

        # Step 3: Move model files and update imports
        if not self.move_model_files_manually_then_rope(source_files, target_app):
            return False

        # Step 4: Update posthog/models/__init__.py imports
        if not self.update_posthog_models_init(source_files, target_app):
            return False

        # Step 5: Update settings
        if not self.update_settings(target_app):
            return False

        # Step 6: Generate migrations
        success, target_migration, posthog_migration = self.generate_migrations(target_app)
        if not success:
            return False

        # Step 7: Edit migrations with Claude
        if not self.edit_migrations_with_claude(target_migration, posthog_migration):
            return False

        # Step 8: Test
        if not self.run_tests(target_app):
            return False

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

    # Check for single mode flag
    single_mode = "--single" in sys.argv

    migrator = ModelMigrator()
    migrator.run_all_migrations(single_mode=single_mode)
