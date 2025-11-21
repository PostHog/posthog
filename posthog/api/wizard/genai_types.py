"""Utility functions for dynamically loading and caching google.genai.types.

This module provides a generic function to import types from google.genai.types
dynamically, caching them so they're only loaded once per server process.
"""

from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    pass

T = TypeVar("T")

# Cache for imported types
_genai_types_cache: dict[str, Any] = {}


def get_genai_type(type_name: str) -> Any:
    """Dynamically import and cache a type from google.genai.types.

    Types are cached globally so they're only imported once per server process.
    This avoids loading heavy google.genai dependencies at module import time.

    Args:
        type_name: The name of the type to import (e.g., "Blob", "Content", "GenerateContentConfig")

    Returns:
        The requested type class

    Example:
        >>> Blob = get_genai_type("Blob")
        >>> blob = Blob(data=b"data", mime_type="image/png")
    """
    global _genai_types_cache

    if type_name not in _genai_types_cache:
        from google.genai.types import (
            Blob,
            Content,
            ContentListUnion,
            GenerateContentConfig,
            Part,
            Schema,
            Type as TypeEnum,
            VideoMetadata,
        )

        type_mapping = {
            "Blob": Blob,
            "Content": Content,
            "ContentListUnion": ContentListUnion,
            "GenerateContentConfig": GenerateContentConfig,
            "Part": Part,
            "Schema": Schema,
            "Type": TypeEnum,
            "TypeEnum": TypeEnum,
            "VideoMetadata": VideoMetadata,
        }

        if type_name not in type_mapping:
            raise ValueError(f"Unknown genai type: {type_name}. " f"Available types: {', '.join(type_mapping.keys())}")

        _genai_types_cache[type_name] = type_mapping[type_name]

    return _genai_types_cache[type_name]


def get_genai_types(*type_names: str) -> tuple[Any, ...]:
    """Dynamically import and cache multiple types from google.genai.types.

    Types are cached globally so they're only imported once per server process.

    Args:
        *type_names: Names of the types to import

    Returns:
        Tuple of the requested type classes in the same order as type_names

    Example:
        >>> Blob, Content, Part = get_genai_types("Blob", "Content", "Part")
    """
    return tuple(get_genai_type(name) for name in type_names)
