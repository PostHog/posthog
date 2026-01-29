"""
Naming convention utilities for database identifiers.

Replaces DLT's NamingConvention with a simplified snake_case converter.
"""

import re


def normalize_identifier(name: str) -> str:
    """Convert string to snake_case, matching DLT's NamingConvention behavior.

    Compatible with dlt.common.normalizers.naming.snake_case.NamingConvention().normalize_identifier()

    Args:
        name: Identifier to normalize

    Returns:
        Snake case identifier

    Examples:
        >>> normalize_identifier("camelCase")
        'camel_case'
        >>> normalize_identifier("PascalCase")
        'pascal_case'
        >>> normalize_identifier("kebab-case")
        'kebab_case'
        >>> normalize_identifier("space case")
        'space_case'
        >>> normalize_identifier("MixedCase123ABC")
        'mixed_case123_abc'
    """
    if not name:
        return "_"

    # Step 1: Handle camelCase and PascalCase
    # Insert underscore before uppercase letters that follow lowercase letters or numbers
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    # Insert underscore before uppercase letters that follow other uppercase letters and precede lowercase letters
    s2 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s1)

    # Step 2: Replace non-alphanumeric characters with underscores
    s3 = re.sub(r"[^a-zA-Z0-9]", "_", s2)

    # Step 3: Collapse multiple underscores into one
    s4 = re.sub(r"_+", "_", s3)

    # Step 4: Convert to lowercase and strip leading/trailing underscores
    result = s4.lower().strip("_")

    # Return underscore if result is empty
    return result or "_"


# Alias for backward compatibility
normalize_column_name = normalize_identifier
