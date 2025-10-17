"""
Type signature generator utilities for HogQL functions with variadic arguments.
"""

from itertools import product
from typing import Optional

from posthog.hogql.ast import IntegerType, StringType
from posthog.hogql.functions.core import AnyConstantType


def generate_variadic_signatures(
    fixed_types: list[AnyConstantType],
    variadic_types: list[AnyConstantType],
    suffix_types: Optional[list[AnyConstantType]] = None,
    min_variadic: int = 0,
    max_variadic: int = 5,
) -> list[tuple[AnyConstantType, ...]]:
    """
    Generate all possible input signature combinations for functions with variadic arguments.

    Args:
        fixed_types: List of fixed parameter types (e.g., [StringType()] for JSON parameter)
        variadic_types: List of possible types for variadic parameters (e.g., [StringType(), IntegerType()])
        suffix_types: List of fixed types after variadic types (optional)
        min_variadic: Minimum number of variadic arguments
        max_variadic: Maximum number of variadic arguments

    Returns:
        List of input signature tuples: (type1, type2, ...)
    """
    signatures = []
    suffix_types = suffix_types or []

    for n_variadic in range(min_variadic, max_variadic + 1):
        if n_variadic == 0:
            # No variadic arguments
            signatures.append(tuple(fixed_types + suffix_types))
        else:
            # Generate all combinations of variadic_types for n_variadic positions
            for combo in product(variadic_types, repeat=n_variadic):
                signature = tuple(fixed_types + list(combo) + suffix_types)
                signatures.append(signature)

    return signatures


def generate_json_path_signatures(
    fixed_types: list[AnyConstantType],
    return_type: AnyConstantType,
    suffix_types: Optional[list[AnyConstantType]] = None,
    min_paths: int = 0,
    max_paths: int = 5,
) -> list[tuple[tuple[AnyConstantType, ...], AnyConstantType]]:
    """
    Generate signature combinations specifically for JSON functions with path arguments.
    Path arguments can be either String (key) or Integer (array index).

    Args:
        fixed_types: Fixed parameter types (e.g., [StringType()] for JSON)
        return_type: The return type for all signatures
        suffix_types: List of fixed types after variadic types (optional)
        min_paths: Minimum number of path arguments (0 = allow no paths)
        max_paths: Maximum number of path arguments

    Returns:
        List of complete signature tuples: ((input_types...), return_type)
    """
    path_types: list[AnyConstantType] = [StringType(), IntegerType()]
    suffix_types = suffix_types or []
    input_signatures = generate_variadic_signatures(fixed_types, path_types, suffix_types, min_paths, max_paths)

    # Add return type to each signature
    return [(sig, return_type) for sig in input_signatures]
