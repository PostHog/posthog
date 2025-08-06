"""
Simplified base class for checkpoint migrations.

Key simplification: Migrations only transform data, they don't touch the database.
This makes them simple, synchronous, and testable.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseMigration(ABC):
    """
    Base class for simple data migrations.

    Migrations should be deterministic, and only deal with data transformation, no database operations.
    Migrations are applied in the checkpoint serializer during deserialization.
    """

    @abstractmethod
    def migrate_data(self, data: dict[str, Any], type_hint: str) -> tuple[dict[str, Any], str]:
        """
        Apply the migration to a data dictionary.

        This is a pure function that transforms data. It should:
        - Not perform any I/O operations
        - Not access the database
        - Be idempotent (safe to run multiple times)
        - Handle missing fields gracefully
        - Can change the type hint for class renames

        Args:
            data: The data dictionary to migrate
            type_hint: The type hint (e.g., "AssistantState", "PartialAssistantState")
                      to help determine if migration applies

        Returns:
            Tuple of (migrated_data, new_type_hint)

        Example:
            # Rename a class
            if type_hint == "OldStateName":
                type_hint = "NewStateName"

            # Add a field
            if type_hint == "AssistantState" and "new_field" not in data:
                data["new_field"] = "default_value"

            return data, type_hint
        """
        pass
