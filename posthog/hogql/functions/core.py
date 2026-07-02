from dataclasses import dataclass
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.ast import (
    ArrayType,
    BooleanType,
    DateTimeType,
    DateType,
    DecimalType,
    FloatType,
    IntegerType,
    IntervalType,
    StringLiteralType,
    StringType,
    TupleType,
    UUIDType,
)
from posthog.hogql.base import ConstantType, UnknownType
from posthog.hogql.errors import QueryError


def validate_function_args(
    args: list[ast.Expr],
    min_args: int,
    max_args: Optional[int],
    function_name: str,
    *,
    function_term="function",
    argument_term="argument",
):
    too_few = len(args) < min_args
    too_many = max_args is not None and len(args) > max_args
    if min_args == max_args and (too_few or too_many):
        raise QueryError(
            f"{function_term.capitalize()} '{function_name}' expects {min_args} {argument_term}{'s' if min_args != 1 else ''}, found {len(args)}"
        )
    if too_few:
        raise QueryError(
            f"{function_term.capitalize()} '{function_name}' expects at least {min_args} {argument_term}{'s' if min_args != 1 else ''}, found {len(args)}"
        )
    if too_many:
        raise QueryError(
            f"{function_term.capitalize()} '{function_name}' expects at most {max_args} {argument_term}{'s' if max_args != 1 else ''}, found {len(args)}"
        )


def validate_clickhouse_format_string(pattern: str, function_name: str) -> None:
    """Validate a ClickHouse ``format()`` pattern's placeholders.

    ClickHouse ``format()`` only supports positional placeholders — empty ``{}`` or a
    numeric index ``{0}`` — with ``{{`` / ``}}`` as literal braces. Python-style specs
    like ``{:,}`` are not supported; passed through, they surface as an opaque
    ClickHouse BAD_ARGUMENTS exception ("Not a number in curly braces"), so reject them
    here with a message that points at the actual problem.
    """
    i = 0
    length = len(pattern)
    while i < length:
        char = pattern[i]
        if char == "{":
            if i + 1 < length and pattern[i + 1] == "{":  # {{ is a literal {
                i += 2
                continue
            end = pattern.find("}", i + 1)
            if end == -1:
                raise QueryError(
                    f"Function '{function_name}' has an unclosed '{{' in its format string. "
                    "It uses positional placeholders like {} or {0}, not Python-style format specs."
                )
            content = pattern[i + 1 : end]
            if content != "" and not (content.isascii() and content.isdigit()):
                raise QueryError(
                    f"Function '{function_name}' does not support the placeholder '{{{content}}}'. "
                    "It uses positional placeholders like {} or {0}, not Python-style format specs such as {:,}."
                )
            i = end + 1
        elif char == "}":
            if i + 1 < length and pattern[i + 1] == "}":  # }} is a literal }
                i += 2
                continue
            raise QueryError(f"Function '{function_name}' has an unmatched '}}' in its format string.")
        else:
            i += 1


Overload = tuple[tuple[type[ConstantType], ...] | type[ConstantType], str]
AnyConstantType = (
    StringType
    | StringLiteralType
    | BooleanType
    | DateType
    | DateTimeType
    | UUIDType
    | ArrayType
    | TupleType
    | DecimalType
    | UnknownType
    | IntegerType
    | FloatType
    | IntervalType
)


@dataclass()
class HogQLFunctionMeta:
    clickhouse_name: str
    min_args: int = 0
    max_args: Optional[int] = 0
    min_params: int = 0
    max_params: Optional[int] = 0
    passthrough_suffix_args_count: int = 0
    aggregate: bool = False
    overloads: Optional[list[Overload]] = None
    """Overloads allow for using a different ClickHouse function depending on the type of the first arg."""
    tz_aware: bool = False
    """Whether the function is timezone-aware. This means the project timezone will be appended as the last arg."""
    case_sensitive: bool = True
    """Not all ClickHouse functions are case-insensitive. See https://clickhouse.com/docs/en/sql-reference/syntax#keywords."""
    signatures: Optional[list[tuple[tuple[AnyConstantType, ...], AnyConstantType]]] = None
    """Signatures allow for specifying the types of the arguments and the return type of the function."""
    suffix_args: Optional[list[ast.Constant]] = None
    """Additional arguments that are added to the end of the arguments provided by the caller"""
    using_placeholder_arguments: bool = False
    using_positional_arguments: bool = False
    parametric_first_arg: bool = False
    """Some ClickHouse functions take a constant string function name as the first argument. Check that it's one of our allowed function names."""
    validates_ch_format_string: bool = False
    """The first argument is a ClickHouse format() pattern. When it's a constant string, validate its placeholders."""
    requires_within_group: bool = False
    """Whether the aggregation requires WITHIN GROUP syntax."""


def compare_types(
    arg_types: list[ConstantType],
    sig_arg_types: tuple[ConstantType, ...],
    args: Optional[list[ast.Expr]] = None,
):
    if len(arg_types) != len(sig_arg_types):
        return False

    for i, (arg_type, sig_arg_type) in enumerate(zip(arg_types, sig_arg_types)):
        if isinstance(sig_arg_type, UnknownType):
            continue
        if isinstance(sig_arg_type, StringLiteralType):
            if not isinstance(arg_type, StringType):
                return False
            if args is not None and i < len(args):
                arg_node = args[i]
                if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str):
                    if arg_node.value.lower() not in sig_arg_type.values:
                        return False
                else:
                    return False
            else:
                return False
            continue
        if not isinstance(arg_type, sig_arg_type.__class__):
            return False
    return True
