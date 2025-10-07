#!/usr/bin/env python3
"""
Custom linter to check and fix `from posthog.settings import ...` statements.

This enforces using `from django.conf import settings` instead of direct imports
from posthog.settings, which is more aligned with Django best practices.
"""

import re
import ast
import sys
import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImportPattern:
    """Base class for different import patterns."""

    filepath: Path
    line_start: int
    line_end: int

    @staticmethod
    def detect(filepath: Path, node: ast.ImportFrom) -> "ImportPattern | None":
        """Factory method to detect and create appropriate pattern instance."""
        raise NotImplementedError

    def remove_import_lines(self, lines: list[str]) -> str:
        """
        Remove the import statement from lines.
        Returns the indentation to use for the django.conf import.
        """
        raise NotImplementedError

    def get_name_mappings(self, settings_submodules: set[str]) -> dict[str, str]:
        """
        Get mapping of old names to new names for text replacement.
        Returns dict like {"DEBUG": "settings.DEBUG"} or {"data_stores": "settings"}.
        """
        raise NotImplementedError


@dataclass
class Pattern1_DirectSettingsImport(ImportPattern):
    """from posthog.settings import DEBUG, TEST"""

    imported_names: list[str]

    @staticmethod
    def detect(filepath: Path, node: ast.ImportFrom) -> "Pattern1_DirectSettingsImport | None":
        if node.module == "posthog.settings":
            return Pattern1_DirectSettingsImport(
                filepath=filepath,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                imported_names=[alias.name for alias in node.names],
            )
        return None

    def remove_import_lines(self, lines: list[str]) -> str:
        indentation = lines[self.line_start - 1][
            : len(lines[self.line_start - 1]) - len(lines[self.line_start - 1].lstrip())
        ]
        for i in range(self.line_start - 1, self.line_end):
            lines[i] = ""
        return indentation

    def get_name_mappings(self, settings_submodules: set[str]) -> dict[str, str]:
        # For submodules like data_stores: map to settings (for data_stores.X -> settings.X)
        # For variables like DEBUG: map to settings.DEBUG
        mappings = {}
        for name in self.imported_names:
            if name in settings_submodules:
                # Submodule: data_stores -> settings (will replace data_stores.X with settings.X)
                mappings[name] = "settings"
            else:
                # Variable: DEBUG -> settings.DEBUG
                mappings[name] = f"settings.{name}"
        return mappings


@dataclass
class Pattern2_SubmoduleSettingsImport(ImportPattern):
    """from posthog.settings.data_stores import CLICKHOUSE_USER"""

    submodule: str
    imported_names: list[str]

    @staticmethod
    def detect(filepath: Path, node: ast.ImportFrom) -> "Pattern2_SubmoduleSettingsImport | None":
        if node.module and node.module.startswith("posthog.settings."):
            submodule = node.module.split(".", 2)[2]  # Extract submodule name
            return Pattern2_SubmoduleSettingsImport(
                filepath=filepath,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                submodule=submodule,
                imported_names=[alias.name for alias in node.names],
            )
        return None

    def remove_import_lines(self, lines: list[str]) -> str:
        indentation = lines[self.line_start - 1][
            : len(lines[self.line_start - 1]) - len(lines[self.line_start - 1].lstrip())
        ]
        for i in range(self.line_start - 1, self.line_end):
            lines[i] = ""
        return indentation

    def get_name_mappings(self, settings_submodules: set[str]) -> dict[str, str]:
        # Variables from submodules: CLICKHOUSE_USER -> settings.CLICKHOUSE_USER
        return {name: f"settings.{name}" for name in self.imported_names}


@dataclass
class Pattern3_SettingsModuleImport(ImportPattern):
    """from posthog import settings"""

    @staticmethod
    def detect(filepath: Path, node: ast.ImportFrom) -> "Pattern3_SettingsModuleImport | None":
        if node.module == "posthog":
            for alias in node.names:
                if alias.name == "settings" and alias.asname is None:
                    return Pattern3_SettingsModuleImport(
                        filepath=filepath,
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                    )
        return None

    def remove_import_lines(self, lines: list[str]) -> str:
        indentation = lines[self.line_start - 1][
            : len(lines[self.line_start - 1]) - len(lines[self.line_start - 1].lstrip())
        ]
        for i in range(self.line_start - 1, self.line_end):
            lines[i] = ""
        return indentation

    def get_name_mappings(self, settings_submodules: set[str]) -> dict[str, str]:
        # No replacement needed - already using settings.X
        return {}


@dataclass
class Pattern4_SettingsModuleAliasImport(ImportPattern):
    """from posthog import settings as app_settings"""

    alias: str

    @staticmethod
    def detect(filepath: Path, node: ast.ImportFrom) -> "Pattern4_SettingsModuleAliasImport | None":
        if node.module == "posthog":
            for alias in node.names:
                if alias.name == "settings" and alias.asname:
                    return Pattern4_SettingsModuleAliasImport(
                        filepath=filepath,
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                        alias=alias.asname,
                    )
        return None

    def remove_import_lines(self, lines: list[str]) -> str:
        indentation = lines[self.line_start - 1][
            : len(lines[self.line_start - 1]) - len(lines[self.line_start - 1].lstrip())
        ]
        for i in range(self.line_start - 1, self.line_end):
            lines[i] = ""
        return indentation

    def get_name_mappings(self, settings_submodules: set[str]) -> dict[str, str]:
        # Replace alias with settings: app_settings -> settings
        return {self.alias: "settings"}


@dataclass
class Pattern5_MultiImportWithSettings(ImportPattern):
    """from posthog import redis, settings (or redis, settings as app_settings)"""

    other_imports: list[str]
    settings_alias: str | None

    @staticmethod
    def detect(filepath: Path, node: ast.ImportFrom) -> "Pattern5_MultiImportWithSettings | None":
        if node.module == "posthog" and len(node.names) > 1:
            settings_alias = None
            other_imports = []
            has_settings = False

            for alias in node.names:
                if alias.name == "settings":
                    has_settings = True
                    settings_alias = alias.asname
                else:
                    other_imports.append(alias.name if not alias.asname else f"{alias.name} as {alias.asname}")

            if has_settings:
                return Pattern5_MultiImportWithSettings(
                    filepath=filepath,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    other_imports=other_imports,
                    settings_alias=settings_alias,
                )
        return None

    def remove_import_lines(self, lines: list[str]) -> str:
        # Don't remove entire line - just remove settings from the import
        indentation = lines[self.line_start - 1][
            : len(lines[self.line_start - 1]) - len(lines[self.line_start - 1].lstrip())
        ]

        # Reconstruct the import without settings
        for i in range(self.line_start - 1, self.line_end):
            line = lines[i]
            # Remove ", settings" or "settings, " or " as alias" variations
            line = re.sub(r",\s*settings(\s+as\s+\w+)?", "", line)
            line = re.sub(r"settings(\s+as\s+\w+)?\s*,\s*", "", line)
            lines[i] = line

        return indentation

    def get_name_mappings(self, settings_submodules: set[str]) -> dict[str, str]:
        # If aliased, replace alias with settings
        if self.settings_alias:
            return {self.settings_alias: "settings"}
        # Otherwise no replacement needed (already using settings.X)
        return {}


def get_settings_submodules() -> set[str]:
    """Get list of posthog/settings submodules by checking filesystem."""
    settings_dir = Path("posthog/settings")
    if not settings_dir.exists():
        return set()

    submodules = set()
    for file in settings_dir.glob("*.py"):
        if file.stem != "__init__":
            submodules.add(file.stem)
    return submodules


def is_excluded_file(filepath: Path) -> bool:
    """Check if file should be excluded from transformation."""
    filepath_str = str(filepath)
    return "posthog/settings/" in filepath_str or filepath_str.endswith("ee/settings.py")


def detect_patterns(filepath: Path, content: str) -> list[ImportPattern]:
    """Detect all import patterns in a file."""
    if is_excluded_file(filepath):
        return []

    try:
        tree = ast.parse(content, filename=str(filepath))
    except SyntaxError:
        return []

    patterns = []
    pattern_classes = [
        Pattern5_MultiImportWithSettings,  # Check multi-import first
        Pattern4_SettingsModuleAliasImport,
        Pattern3_SettingsModuleImport,
        Pattern2_SubmoduleSettingsImport,
        Pattern1_DirectSettingsImport,
    ]

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for pattern_class in pattern_classes:
                if pattern := pattern_class.detect(filepath, node):
                    patterns.append(pattern)
                    break  # First match wins

    return patterns


def fix_file(filepath: Path) -> bool:
    """Fix a file by transforming imports. Returns True if changes were made."""
    content = filepath.read_text()
    patterns = detect_patterns(filepath, content)

    if not patterns:
        return False

    lines = content.splitlines(keepends=True)

    # Check if django.conf import already exists
    has_django_import = "from django.conf import settings" in content

    # Get settings submodules for name mapping
    settings_submodules = get_settings_submodules()

    # Collect all name mappings
    all_name_mappings = {}
    for pattern in patterns:
        all_name_mappings.update(pattern.get_name_mappings(settings_submodules))

    # Remove import lines and collect indentation
    indentation = None
    for pattern in patterns:
        if indentation is None:
            indentation = pattern.remove_import_lines(lines)
        else:
            pattern.remove_import_lines(lines)

    # Add django.conf import if not present
    if not has_django_import and indentation is not None:
        # Find first non-empty line index to insert import
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.strip() and not lines[i].startswith("#"):
                insert_idx = i
                break

        lines.insert(insert_idx, "from django.conf import settings\n")

    # Apply name replacements
    modified_lines = []
    for line in lines:
        # Skip empty lines, comments, and import statements
        if not line or line.strip().startswith("#") or line.strip().startswith(("import ", "from ")):
            modified_lines.append(line)
            continue

        modified_line = line
        for old_name, new_name in sorted(all_name_mappings.items(), key=lambda x: len(x[0]), reverse=True):
            if new_name == "settings":
                # Submodule replacement: data_stores.X -> settings.X
                pattern = r"\b" + re.escape(old_name) + r"\."
                modified_line = re.sub(pattern, "settings.", modified_line)
            else:
                # Variable or alias replacement: DEBUG -> settings.DEBUG or app_settings -> settings
                pattern = r"\b" + re.escape(old_name) + r"\b"
                modified_line = re.sub(pattern, new_name, modified_line)

        modified_lines.append(modified_line)

    # Write back
    filepath.write_text("".join(modified_lines))
    return True


def find_python_files(paths: list[Path] | None = None) -> list[Path]:
    """Find all Python files to check."""
    if paths:
        python_files = []
        for path in paths:
            if path.is_file() and path.suffix == ".py":
                python_files.append(path)
            elif path.is_dir() or str(path) == ".":
                search_dir = path if path.is_dir() else Path(".")
                for directory in ["posthog", "ee", "products", "dags"]:
                    dir_path = search_dir / directory
                    if dir_path.exists():
                        python_files.extend(dir_path.rglob("*.py"))
        return python_files

    # Default to checking posthog/, ee/, products/, dags/
    base_dir = Path(__file__).parent.parent
    python_files = []
    for directory in ["posthog", "ee", "products", "dags"]:
        dir_path = base_dir / directory
        if dir_path.exists():
            python_files.extend(dir_path.rglob("*.py"))
    return python_files


def check_file(filepath: Path) -> list[str]:
    """Check a file and return list of issues."""
    content = filepath.read_text()
    patterns = detect_patterns(filepath, content)
    return [f"{filepath}:{p.line_start}:0: Use 'from django.conf import settings' instead" for p in patterns]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check for posthog.settings imports and enforce django.conf.settings usage"
    )
    parser.add_argument("--fix", action="store_true", help="Automatically fix issues")
    parser.add_argument("files", nargs="*", type=Path, help="Files to check (default: all Python files)")

    args = parser.parse_args()

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
            all_issues.extend(check_file(filepath))

        if all_issues:
            for issue in all_issues:
                print(issue)  # noqa: T201

            print(f"\n✗ Found {len(all_issues)} issue(s)")  # noqa: T201
            print("Run with --fix to automatically fix these issues")  # noqa: T201
            return 1
        else:
            print("✓ No issues found")  # noqa: T201
            return 0


if __name__ == "__main__":
    sys.exit(main())
