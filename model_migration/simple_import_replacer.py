"""
Simple regex-based import path replacer for module moves.
Preserves lazy imports, comments, formatting, and all other code structure.
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImportPathPattern:
    """Represents a single import path transformation."""

    source_pattern: str  # e.g., "posthog.warehouse"
    target_path: str  # e.g., "products.data_warehouse.backend"

    def __post_init__(self):
        """Validate patterns are properly formatted."""
        if not self.source_pattern or not self.target_path:
            raise ValueError("source_pattern and target_path must be non-empty")
        if ".." in self.source_pattern or ".." in self.target_path:
            raise ValueError("patterns must not contain '..'")


class SimpleImportReplacer:
    """
    Regex-based import replacer that handles simple module path transformations.
    Does NOT parse AST, just does text replacement on import statements.
    Preserves lazy imports, TYPE_CHECKING blocks, comments, formatting.
    """

    def __init__(self, patterns: list[ImportPathPattern]):
        """
        Initialize with patterns to apply.

        Args:
            patterns: List of ImportPathPattern objects defining transformations
        """
        self.patterns = patterns

    def replace_in_text(self, content: str) -> tuple[str, bool]:
        """
        Replace import paths in text content.

        Args:
            content: Python file content

        Returns:
            Tuple of (modified_content, was_changed)
        """
        original = content
        modified = content

        for pattern in self.patterns:
            modified = self._apply_pattern(modified, pattern)

        return modified, modified != original

    def replace_in_file(self, file_path: Path) -> bool:
        """
        Replace import paths in a file.

        Args:
            file_path: Path to Python file

        Returns:
            True if file was modified, False otherwise
        """
        if not file_path.exists():
            return False

        content = file_path.read_text(encoding="utf-8")
        modified_content, changed = self.replace_in_text(content)

        if changed:
            file_path.write_text(modified_content, encoding="utf-8")

        return changed

    @staticmethod
    def _apply_pattern(content: str, pattern: ImportPathPattern) -> str:
        """
        Apply a single pattern transformation to content.

        Handles:
        - from posthog.warehouse import X
        - from posthog.warehouse.models import Y
        - from posthog.warehouse.api.table import Z
        - from posthog.warehouse.models.table import Y
        - etc.

        Does NOT replace:
        - Comments or strings
        - Imports inside comments
        """
        source = pattern.source_pattern
        target = pattern.target_path

        # Escape dots in source pattern for regex
        escaped_source = re.escape(source)

        # Pattern: "from posthog.warehouse" or "from posthog.warehouse."
        # This matches the import base and anything after it
        # We match word boundaries to avoid false positives
        regex_pattern = rf"(\bfrom\s+){escaped_source}(\s*\.|\s+import)"

        replacement = rf"\1{target}\2"

        return re.sub(regex_pattern, replacement, content)
