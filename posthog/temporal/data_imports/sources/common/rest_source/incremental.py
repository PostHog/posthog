"""
Incremental loading state tracking for REST API sources.

Replaces DLT's Incremental class with a simplified version.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Incremental:
    """Tracks cursor state for incremental loading.

    Compatible with dlt.extract.incremental.Incremental
    """

    cursor_path: str
    initial_value: Any
    last_value: Optional[Any] = None
    end_value: Optional[Any] = None

    def __post_init__(self):
        """Initialize last_value to initial_value if not set."""
        if self.last_value is None:
            self.last_value = self.initial_value

    def update(self, item: dict) -> None:
        """Update cursor state from an item.

        Args:
            item: Data item containing cursor field
        """
        from .jsonpath_utils import extract_value

        value = extract_value(item, self.cursor_path)
        if value is not None:
            self.last_value = value


def create_incremental(
    cursor_path: str,
    initial_value: Any,
    end_value: Optional[Any] = None,
) -> Incremental:
    """Create an Incremental instance.

    Args:
        cursor_path: JSONPath to cursor field in response items
        initial_value: Starting cursor value
        end_value: Optional ending cursor value

    Returns:
        Incremental instance
    """
    return Incremental(
        cursor_path=cursor_path,
        initial_value=initial_value,
        end_value=end_value,
    )
