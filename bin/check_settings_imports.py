#!/usr/bin/env python3
"""
Custom linter to check and fix `from posthog.settings import ...` statements.

This script enforces the Django best practice of using `from django.conf import settings`
instead of directly importing from the settings module.

Usage:
    python bin/check_settings_imports.py [--fix] [files...]

    --fix: Automatically fix issues
    files: Specific files to check (defaults to all .py files in posthog/, ee/, products/, dags/)
"""

import ast
import sys
import argparse
from pathlib import Path
from typing import NamedTuple


class Issue(NamedTuple):
    """Represents a linting issue found in a file."""

    file: Path
    line: int
    end_line: int
    col: int
    imported_names: list[str]
    message: str
    is_module_import: bool  # True if "from posthog import settings", False if "from posthog.settings import X"


class SettingsImportChecker(ast.NodeVisitor):
    """AST visitor that detects imports from posthog.settings."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.issues: list[Issue] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Check ImportFrom nodes for posthog.settings imports."""
        # Skip if this is a settings file itself
        if self._is_settings_file():
            self.generic_visit(node)
            return

        # Check for "from posthog.settings import ..." or "from posthog.settings.submodule import ..."
        if node.module and node.module.startswith("posthog.settings"):
            imported_names = [alias.name for alias in node.names]
            self.issues.append(
                Issue(
                    file=self.filepath,
                    line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    col=node.col_offset,
                    imported_names=imported_names,
                    message=(
                        f"Use 'from django.conf import settings' instead of "
                        f"'from {node.module} import {', '.join(imported_names)}'"
                    ),
                    is_module_import=False,
                )
            )
        # Check for "from posthog import settings"
        elif node.module == "posthog":
            for alias in node.names:
                if alias.name == "settings":
                    self.issues.append(
                        Issue(
                            file=self.filepath,
                            line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                            col=node.col_offset,
                            imported_names=["settings"],
                            message="Use 'from django.conf import settings' instead of 'from posthog import settings'",
                            is_module_import=True,
                        )
                    )
        self.generic_visit(node)

    def _is_settings_file(self) -> bool:
        """Check if this file is part of the settings package."""
        return "posthog/settings/" in str(self.filepath)


class SettingsImportTransformer(ast.NodeTransformer):
    """AST transformer that fixes posthog.settings imports."""

    def __init__(self, imported_names_map: dict[int, list[str]]):
        self.imported_names_map = imported_names_map
        self.all_imported_names = {name for names in imported_names_map.values() for name in names}
        self.has_django_settings_import = False
        self.django_import_added = False

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom | None:
        """Remove posthog.settings imports and add django.conf import if needed."""
        # Check if this is django.conf import
        if node.module == "django.conf":
            for alias in node.names:
                if alias.name == "settings":
                    self.has_django_settings_import = True

        # Remove posthog.settings imports
        if node.module and node.module.startswith("posthog.settings"):
            # Add django.conf import once at the first posthog.settings import location
            if not self.has_django_settings_import and not self.django_import_added:
                self.django_import_added = True
                return ast.ImportFrom(
                    module="django.conf",
                    names=[ast.alias(name="settings", asname=None)],
                    level=0,
                )
            # Skip this import
            return None

        return node

    def visit_Name(self, node: ast.Name) -> ast.Name | ast.Attribute:
        """Replace bare name usage with settings.NAME."""
        # If this name is one of the imported settings, replace it
        if node.id in self.all_imported_names:
            # Create settings.NAME attribute access
            return ast.Attribute(
                value=ast.Name(id="settings", ctx=ast.Load()),
                attr=node.id,
                ctx=node.ctx,
            )
        return node


class SettingsImportFixer:
    """Fixes posthog.settings imports using surgical text replacements."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.content = filepath.read_text()
        self.lines = self.content.splitlines(keepends=True)
        try:
            self.tree = ast.parse(self.content, filename=str(filepath))
        except SyntaxError as e:
            print(f"Syntax error in {filepath}: {e}", file=sys.stderr)  # noqa: T201
            self.tree = None

    def fix(self) -> bool:
        """
        Fix all posthog.settings imports in the file.
        Returns True if any changes were made.
        """
        if self.tree is None:
            return False

        checker = SettingsImportChecker(self.filepath)
        checker.visit(self.tree)

        if not checker.issues:
            return False

        # Collect imported names that need replacement (only from posthog.settings.X imports, not module imports)
        names_to_replace = set()
        for issue in checker.issues:
            if not issue.is_module_import:
                names_to_replace.update(issue.imported_names)

        # Check if django.conf import already exists
        has_django_settings_import = self._has_django_settings_import()

        # Step 1: Remove posthog.settings import lines
        lines_to_remove = set()
        for issue in checker.issues:
            for line_num in range(issue.line - 1, issue.end_line):
                lines_to_remove.add(line_num)

        # Step 2: Replace name usages with settings.NAME (only for non-module imports)
        new_lines = []
        django_import_added = False
        for i, line in enumerate(self.lines):
            if i in lines_to_remove:
                # Add django.conf import at the first removed line, preserving indentation
                if not has_django_settings_import and not django_import_added:
                    # Get indentation from the removed line
                    indentation = line[: len(line) - len(line.lstrip())]
                    new_lines.append(f"{indentation}from django.conf import settings\n")
                    django_import_added = True
                continue

            # Replace bare names with settings.NAME (only for names imported from posthog.settings.X)
            modified_line = self._replace_names_in_line(line, names_to_replace)
            new_lines.append(modified_line)

        # Write back
        self.filepath.write_text("".join(new_lines))
        return True

    def _has_django_settings_import(self) -> bool:
        """Check if the file already has 'from django.conf import settings'."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "django.conf":
                    for alias in node.names:
                        if alias.name == "settings":
                            return True
        return False

    def _replace_names_in_line(self, line: str, names: set[str]) -> str:
        """Replace bare name usages with settings.NAME."""
        import re

        # Skip if line is a comment or string
        stripped = line.lstrip()
        if stripped.startswith("#"):
            return line

        # For each imported name, replace it with settings.NAME
        # Use word boundaries to avoid partial matches
        modified = line
        for name in sorted(names, key=len, reverse=True):  # Longer names first
            # Match the name as a whole word, not as part of another identifier
            pattern = r"\b" + re.escape(name) + r"\b"
            modified = re.sub(pattern, f"settings.{name}", modified)

        return modified


def find_python_files(paths: list[Path] | None = None) -> list[Path]:
    """Find all Python files to check."""
    if paths:
        return [p for p in paths if p.suffix == ".py"]

    # Default to checking posthog/, ee/, products/, dags/
    base_dir = Path(__file__).parent.parent
    python_files = []
    for directory in ["posthog", "ee", "products", "dags"]:
        dir_path = base_dir / directory
        if dir_path.exists():
            python_files.extend(dir_path.rglob("*.py"))
    return python_files


def check_file(filepath: Path) -> list[Issue]:
    """Check a single file for posthog.settings imports."""
    try:
        content = filepath.read_text()
        tree = ast.parse(content, filename=str(filepath))
        checker = SettingsImportChecker(filepath)
        checker.visit(tree)
        return checker.issues
    except SyntaxError:
        # Skip files with syntax errors
        return []


def fix_file(filepath: Path) -> bool:
    """Fix a single file. Returns True if changes were made."""
    try:
        fixer = SettingsImportFixer(filepath)
        return fixer.fix()
    except Exception as e:
        print(f"Error fixing {filepath}: {e}", file=sys.stderr)  # noqa: T201
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check for posthog.settings imports and enforce django.conf.settings usage"
    )
    parser.add_argument("--fix", action="store_true", help="Automatically fix issues")
    parser.add_argument("files", nargs="*", type=Path, help="Files to check (default: all Python files)")

    args = parser.parse_args()

    # Find files to check
    files = find_python_files(args.files if args.files else None)

    if args.fix:
        # Fix mode
        fixed_count = 0
        for filepath in files:
            if fix_file(filepath):
                print(f"Fixed: {filepath}")  # noqa: T201
                fixed_count += 1

        if fixed_count > 0:
            print(f"\n✓ Fixed {fixed_count} file(s)")  # noqa: T201
            print("Run 'ruff format .' to format the fixed files")  # noqa: T201
            return 0
        else:
            print("✓ No issues found")  # noqa: T201
            return 0
    else:
        # Check mode
        all_issues = []
        for filepath in files:
            issues = check_file(filepath)
            all_issues.extend(issues)

        if all_issues:
            for issue in all_issues:
                print(f"{issue.file}:{issue.line}:{issue.col}: {issue.message}")  # noqa: T201

            print(f"\n✗ Found {len(all_issues)} issue(s) in {len({i.file for i in all_issues})} file(s)")  # noqa: T201
            print("Run with --fix to automatically fix these issues")  # noqa: T201
            return 1
        else:
            print("✓ No issues found")  # noqa: T201
            return 0


if __name__ == "__main__":
    sys.exit(main())
