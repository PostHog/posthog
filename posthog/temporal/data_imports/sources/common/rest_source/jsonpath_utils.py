"""
JSONPath utilities for extracting data from API responses.

Uses jsonpath-ng library to provide DLT-compatible JSONPath functionality.
"""

from typing import Any, Optional

from jsonpath_ng import parse
from jsonpath_ng.exceptions import JsonPathParserError

# Type alias for JSONPath strings
TJsonPath = str


def compile_path(path: str):
    """Compile a JSONPath expression.

    Compatible with dlt.common.jsonpath.compile_path

    Args:
        path: JSONPath expression (e.g., "data.items", "data[*].id")

    Returns:
        Compiled JSONPath expression
    """
    try:
        return parse(path)
    except JsonPathParserError as e:
        raise ValueError(f"Invalid JSONPath expression '{path}': {e}")


def find_values(path: str, data: Any) -> list[Any]:
    """Find all values matching a JSONPath expression.

    Compatible with dlt.common.jsonpath.find_values

    Args:
        path: JSONPath expression
        data: Data to search (dict, list, etc.)

    Returns:
        List of matching values
    """
    try:
        compiled_path = compile_path(path)
        matches = compiled_path.find(data)
        return [match.value for match in matches]
    except (JsonPathParserError, AttributeError, KeyError, TypeError):
        return []


def extract_value(data: Any, path: Optional[str]) -> Any:
    """Extract value(s) from data using JSONPath.

    When the path contains wildcards (e.g., "data[*].item"), returns a list of all matches.
    Otherwise returns a single value.

    Args:
        data: Data to extract from
        path: JSONPath expression, or None to return data as-is

    Returns:
        Extracted value(s), or None if not found
    """
    if path is None or path == "$":
        return data

    values = find_values(path, data)

    # If we have multiple values (wildcard), return them all
    if len(values) > 1:
        return values

    # Single value or no values
    return values[0] if values else None
