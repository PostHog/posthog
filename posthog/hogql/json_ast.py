"""
JSON AST Deserializer

Converts JSON strings returned by the C++ HogQL parser back into Python AST objects.
"""

import json
from typing import Any, get_type_hints

from posthog.hogql import ast


def deserialize_ast(json_str: str) -> ast.AST:
    """Deserialize a JSON string into a Python AST object."""
    data = json.loads(json_str)
    return _deserialize_node(data)


def _deserialize_node(data: Any) -> Any:
    """Recursively deserialize a JSON node into an AST object."""
    if data is None:
        return None

    if isinstance(data, list):
        return [_deserialize_node(item) for item in data]

    if not isinstance(data, dict):
        # Primitive value (string, int, float, bool)
        # Handle special float values that JSON can't represent
        if isinstance(data, str):
            if data == "Infinity":
                return float("inf")
            elif data == "-Infinity":
                return float("-inf")
            elif data == "NaN":
                return float("nan")
        return data

    # Check if this is an error response
    if "error" in data and data["error"] is True:
        # This is an error from the parser - convert to the appropriate exception type
        from posthog.hogql.errors import (
            ExposedHogQLError,
            SyntaxError as HogQLSyntaxError,
        )

        error_type = data.get("type", "Error")
        message = data.get("message", "Unknown error")
        start = data.get("start", {})
        end = data.get("end", {})

        # Map error types to Python exceptions
        # Only raise custom SyntaxError for reserved keyword errors, everything else is ExposedHogQLError
        if error_type == "SyntaxError" and "reserved keyword" in message:
            raise HogQLSyntaxError(message, start=start.get("offset"), end=end.get("offset"))
        else:
            # All other errors (including most SyntaxErrors) are ExposedHogQLError
            raise ExposedHogQLError(message, start=start.get("offset"), end=end.get("offset"))

    # Must be a dict with a "node" field
    if "node" not in data:
        raise ValueError(f"Invalid AST node: missing 'node' field in {data}")

    node_type = data["node"]

    # Map node types to AST classes
    node_map = {
        "Alias": ast.Alias,
        "And": ast.And,
        "ArithmeticOperation": ast.ArithmeticOperation,
        "Array": ast.Array,
        "ArrayAccess": ast.ArrayAccess,
        "BetweenExpr": ast.CompareOperation,  # BetweenExpr is represented as CompareOperation
        "Block": ast.Block,
        "CTE": ast.CTE,
        "Call": ast.Call,
        "CompareOperation": ast.CompareOperation,
        "Constant": ast.Constant,
        "Dict": ast.Dict,
        "ExprCall": ast.ExprCall,
        "ExprStatement": ast.ExprStatement,
        "Field": ast.Field,
        "ForInStatement": ast.ForInStatement,
        "ForStatement": ast.ForStatement,
        "Function": ast.Function,
        "HogQLXAttribute": ast.HogQLXAttribute,
        "HogQLXTag": ast.HogQLXTag,
        "IfStatement": ast.IfStatement,
        "JoinConstraint": ast.JoinConstraint,
        "JoinExpr": ast.JoinExpr,
        "Lambda": ast.Lambda,
        "LimitByExpr": ast.LimitByExpr,
        "Not": ast.Not,
        "Or": ast.Or,
        "OrderExpr": ast.OrderExpr,
        "Placeholder": ast.Placeholder,
        "Program": ast.Program,
        "RatioExpr": ast.RatioExpr,
        "ReturnStatement": ast.ReturnStatement,
        "SampleExpr": ast.SampleExpr,
        "SelectQuery": ast.SelectQuery,
        "SelectSetNode": ast.SelectSetNode,
        "SelectSetQuery": ast.SelectSetQuery,
        "ThrowStatement": ast.ThrowStatement,
        "TryCatchStatement": ast.TryCatchStatement,
        "Tuple": ast.Tuple,
        "TupleAccess": ast.TupleAccess,
        "VariableAssignment": ast.VariableAssignment,
        "VariableDeclaration": ast.VariableDeclaration,
        "WhileStatement": ast.WhileStatement,
        "WindowExpr": ast.WindowExpr,
        "WindowFrameExpr": ast.WindowFrameExpr,
        "WindowFunction": ast.WindowFunction,
    }

    ast_class = node_map.get(node_type)
    if ast_class is None:
        raise ValueError(f"Unknown AST node type: {node_type}")

    # Get type hints for this class to check for enums
    try:
        type_hints = get_type_hints(ast_class)
    except Exception:
        type_hints = {}

    # Build kwargs for the AST class constructor
    kwargs = {}
    for key, value in data.items():
        if key == "node":
            # Skip node type field - we already used it
            continue

        # Handle position fields (start/end) - convert from position object to offset integer
        if key in ("start", "end") and isinstance(value, dict) and "offset" in value:
            kwargs[key] = value["offset"]
            continue

        # Handle dict fields that map string keys to AST nodes (like window_exprs, ctes, limit_by.expressions)
        # These dicts don't have a "node" field themselves - they're just containers
        if (
            isinstance(value, dict)
            and "node" not in value
            and key in ("window_exprs", "ctes", "limit_by", "expressions")
        ):
            # This is a dict mapping strings to AST nodes - deserialize the values
            deserialized_value = {k: _deserialize_node(v) for k, v in value.items()}
        else:
            # Recursively deserialize nested nodes
            deserialized_value = _deserialize_node(value)

        # Check if this field should be an enum
        if key in type_hints:
            field_type = type_hints[key]
            # Check if it's an enum type by checking for __members__
            if hasattr(field_type, "__members__") and isinstance(deserialized_value, str):
                # Convert string to enum
                try:
                    deserialized_value = field_type[deserialized_value]
                except KeyError:
                    pass  # If conversion fails, keep the string value

        kwargs[key] = deserialized_value

    # Create the AST object
    return ast_class(**kwargs)
