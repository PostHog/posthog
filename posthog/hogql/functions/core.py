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


Overload = tuple[tuple[type[ConstantType], ...] | type[ConstantType], str]
AnyConstantType = (
    StringType
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


def compare_types(arg_types: list[ConstantType], sig_arg_types: tuple[ConstantType, ...]):
    if len(arg_types) != len(sig_arg_types):
        return False

    return all(
        isinstance(sig_arg_type, UnknownType) or isinstance(arg_type, sig_arg_type.__class__)
        for arg_type, sig_arg_type in zip(arg_types, sig_arg_types)
    )
