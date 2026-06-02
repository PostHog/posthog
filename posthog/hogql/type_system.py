from __future__ import annotations

import re
import dataclasses
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Optional, cast

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect

if TYPE_CHECKING:
    from posthog.hogql.database.models import DatabaseField
    from posthog.hogql.functions.core import HogQLFunctionMeta


type RuntimeTypeFamily = Literal[
    "unknown",
    "integer",
    "float",
    "decimal",
    "string",
    "fixed_string",
    "uuid",
    "boolean",
    "date",
    "datetime",
    "interval",
    "array",
    "tuple",
    "map",
    "json",
    "enum",
    "aggregate_state",
]
type RuntimeTypeDialect = Literal["common", "clickhouse", "postgres", "duckdb"]


class ComparisonCompatibility(StrEnum):
    DEFINITELY_COMPATIBLE = "definitely_compatible"
    CHEAP_CAST = "cheap_cast"
    EXPENSIVE_CAST = "expensive_cast"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RuntimeType:
    family: RuntimeTypeFamily
    nullable: bool = True
    dialect: RuntimeTypeDialect = "common"
    signed: Optional[bool] = None
    bits: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None
    timezone: Optional[str] = None
    item_type: Optional[RuntimeType] = None
    item_types: tuple[RuntimeType, ...] = field(default_factory=tuple)
    field_names: tuple[Optional[str], ...] = field(default_factory=tuple)
    key_type: Optional[RuntimeType] = None
    value_type: Optional[RuntimeType] = None
    wrapped_type: Optional[RuntimeType] = None
    source: Optional[str] = None

    def non_nullable(self) -> RuntimeType:
        return dataclasses.replace(self, nullable=False)

    def with_nullable(self, nullable: bool) -> RuntimeType:
        return dataclasses.replace(self, nullable=nullable)

    def display(self) -> str:
        inner = self._display_inner()
        return f"Nullable({inner})" if self.nullable else inner

    def debug_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "family": self.family,
            "nullable": self.nullable,
            "dialect": self.dialect,
        }
        for key in ("signed", "bits", "precision", "scale", "timezone", "source"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        if self.item_type is not None:
            data["item_type"] = self.item_type.debug_dict()
        if self.item_types:
            data["item_types"] = [item.debug_dict() for item in self.item_types]
        if self.field_names:
            data["field_names"] = list(self.field_names)
        if self.key_type is not None:
            data["key_type"] = self.key_type.debug_dict()
        if self.value_type is not None:
            data["value_type"] = self.value_type.debug_dict()
        if self.wrapped_type is not None:
            data["wrapped_type"] = self.wrapped_type.debug_dict()
        return data

    def _display_inner(self) -> str:
        if self.family == "integer":
            prefix = "Int" if self.signed is not False else "UInt"
            return f"{prefix}{self.bits}" if self.bits is not None else "Integer"
        if self.family == "float":
            return f"Float{self.bits}" if self.bits is not None else "Float"
        if self.family == "decimal":
            if self.precision is not None and self.scale is not None:
                return f"Decimal({self.precision}, {self.scale})"
            return "Decimal"
        if self.family == "fixed_string":
            return f"FixedString({self.bits})" if self.bits is not None else "FixedString"
        if self.family == "datetime":
            if self.precision is not None and self.timezone is not None:
                return f"DateTime64({self.precision}, '{self.timezone}')"
            if self.precision is not None:
                return f"DateTime64({self.precision})"
            if self.timezone is not None:
                return f"DateTime('{self.timezone}')"
            return "DateTime"
        if self.family == "array":
            item_type = self.item_type.display() if self.item_type is not None else "Unknown"
            return f"Array({item_type})"
        if self.family == "tuple":
            parts = []
            for index, item_type in enumerate(self.item_types):
                name = self.field_names[index] if index < len(self.field_names) else None
                parts.append(f"{name} {item_type.display()}" if name else item_type.display())
            return f"Tuple({', '.join(parts)})"
        if self.family == "map":
            key = self.key_type.display() if self.key_type is not None else "Unknown"
            value = self.value_type.display() if self.value_type is not None else "Unknown"
            return f"Map({key}, {value})"
        if self.family == "aggregate_state":
            wrapped = self.wrapped_type.display() if self.wrapped_type is not None else "Unknown"
            return f"AggregateState({wrapped})"
        if self.family == "json":
            return "JSON"
        if self.family == "uuid":
            return "UUID"
        if self.family == "boolean":
            return "Boolean"
        return self.family.title().replace("_", "")


UNKNOWN_RUNTIME_TYPE = RuntimeType(family="unknown")
STRING_RUNTIME_TYPE = RuntimeType(family="string")
BOOLEAN_RUNTIME_TYPE = RuntimeType(family="boolean")
INTEGER_RUNTIME_TYPE = RuntimeType(family="integer", signed=True, bits=64)
FLOAT_RUNTIME_TYPE = RuntimeType(family="float", bits=64)
DATE_RUNTIME_TYPE = RuntimeType(family="date")
DATETIME_RUNTIME_TYPE = RuntimeType(family="datetime")


_INTEGER_RE = re.compile(r"^(U?Int)(8|16|32|64|128|256)$", re.IGNORECASE)
_FLOAT_RE = re.compile(r"^Float(32|64)$", re.IGNORECASE)
_DECIMAL_RE = re.compile(r"^Decimal(?:32|64|128|256)?$", re.IGNORECASE)


def runtime_type_from_constant_type(constant_type: ast.ConstantType) -> RuntimeType:
    nullable = constant_type.nullable
    if isinstance(constant_type, ast.UnknownType):
        return UNKNOWN_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(constant_type, ast.StringJSONType):
        return RuntimeType(family="json", nullable=nullable)
    if isinstance(constant_type, ast.StringArrayType):
        return RuntimeType(family="array", nullable=nullable, item_type=STRING_RUNTIME_TYPE)
    if isinstance(constant_type, ast.StringType):
        return STRING_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(constant_type, ast.BooleanType):
        return BOOLEAN_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(constant_type, ast.IntegerType):
        return INTEGER_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(constant_type, ast.FloatType):
        return FLOAT_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(constant_type, ast.DecimalType):
        return RuntimeType(family="decimal", nullable=nullable)
    if isinstance(constant_type, ast.DateType):
        return DATE_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(constant_type, ast.DateTimeType):
        return DATETIME_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(constant_type, ast.UUIDType):
        return RuntimeType(family="uuid", nullable=nullable)
    if isinstance(constant_type, ast.IntervalType):
        return RuntimeType(family="interval", nullable=nullable)
    if isinstance(constant_type, ast.ArrayType):
        return RuntimeType(
            family="array",
            nullable=nullable,
            item_type=runtime_type_from_constant_type(constant_type.item_type),
        )
    if isinstance(constant_type, ast.TupleType):
        return RuntimeType(
            family="tuple",
            nullable=nullable,
            item_types=tuple(runtime_type_from_constant_type(item) for item in constant_type.item_types),
        )
    return UNKNOWN_RUNTIME_TYPE.with_nullable(nullable)


def constant_type_from_runtime_type(runtime_type: RuntimeType) -> ast.ConstantType:
    nullable = runtime_type.nullable
    if runtime_type.family == "integer":
        return ast.IntegerType(nullable=nullable)
    if runtime_type.family == "float":
        return ast.FloatType(nullable=nullable)
    if runtime_type.family == "decimal":
        return ast.DecimalType(nullable=nullable)
    if runtime_type.family in ("string", "fixed_string", "enum"):
        return ast.StringType(nullable=nullable)
    if runtime_type.family == "json":
        return ast.StringJSONType(nullable=nullable)
    if runtime_type.family == "boolean":
        return ast.BooleanType(nullable=nullable)
    if runtime_type.family == "date":
        return ast.DateType(nullable=nullable)
    if runtime_type.family == "datetime":
        return ast.DateTimeType(nullable=nullable)
    if runtime_type.family == "uuid":
        return ast.UUIDType(nullable=nullable)
    if runtime_type.family == "interval":
        return ast.IntervalType(nullable=nullable)
    if runtime_type.family == "array":
        item_type = constant_type_from_runtime_type(runtime_type.item_type or UNKNOWN_RUNTIME_TYPE)
        return ast.ArrayType(nullable=nullable, item_type=item_type)
    if runtime_type.family == "tuple":
        return ast.TupleType(
            nullable=nullable,
            item_types=[constant_type_from_runtime_type(item) for item in runtime_type.item_types],
        )
    return ast.UnknownType(nullable=nullable)


def runtime_type_from_database_field(database_field: DatabaseField) -> RuntimeType:
    from posthog.hogql.database.models import (  # noqa: PLC0415 - avoids importing database models during type-system startup
        BooleanDatabaseField,
        DateDatabaseField,
        DateTimeDatabaseField,
        DecimalDatabaseField,
        FloatArrayDatabaseField,
        FloatDatabaseField,
        IntegerDatabaseField,
        StringArrayDatabaseField,
        StringDatabaseField,
        StringJSONDatabaseField,
        StructDatabaseField,
        UUIDDatabaseField,
    )

    nullable = database_field.is_nullable()
    if isinstance(database_field, IntegerDatabaseField):
        return INTEGER_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(database_field, FloatDatabaseField):
        return FLOAT_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(database_field, DecimalDatabaseField):
        return RuntimeType(family="decimal", nullable=nullable)
    if isinstance(database_field, StringJSONDatabaseField):
        return RuntimeType(family="json", nullable=nullable)
    if isinstance(database_field, StringArrayDatabaseField):
        return RuntimeType(family="array", nullable=nullable, item_type=STRING_RUNTIME_TYPE)
    if isinstance(database_field, FloatArrayDatabaseField):
        return RuntimeType(family="array", nullable=nullable, item_type=FLOAT_RUNTIME_TYPE)
    if isinstance(database_field, StringDatabaseField):
        return STRING_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(database_field, DateDatabaseField):
        return DATE_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(database_field, DateTimeDatabaseField):
        return DATETIME_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(database_field, BooleanDatabaseField):
        return BOOLEAN_RUNTIME_TYPE.with_nullable(nullable)
    if isinstance(database_field, UUIDDatabaseField):
        return RuntimeType(family="uuid", nullable=nullable)
    if isinstance(database_field, StructDatabaseField):
        return RuntimeType(
            family="tuple",
            nullable=nullable,
            item_types=tuple(runtime_type_from_database_field(field) for field in database_field.fields.values()),
            field_names=tuple(database_field.fields.keys()),
        )
    return runtime_type_from_constant_type(database_field.get_constant_type())


def parse_sql_runtime_type(type_name: str, dialect: HogQLDialect = "clickhouse") -> RuntimeType:
    if dialect == "clickhouse":
        return parse_clickhouse_type(type_name)
    normalized = type_name.strip().lower()
    nullable = "not null" not in normalized
    if normalized in {"boolean", "bool"}:
        return RuntimeType(family="boolean", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized in {"integer", "int", "bigint", "smallint"}:
        return RuntimeType(family="integer", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized in {"real", "double precision", "double", "float"}:
        return RuntimeType(family="float", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized.startswith("decimal") or normalized.startswith("numeric"):
        return RuntimeType(family="decimal", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized in {"text", "varchar", "character varying", "char", "character", "uuid"}:
        family: RuntimeTypeFamily = "uuid" if normalized == "uuid" else "string"
        return RuntimeType(family=family, nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized == "date":
        return RuntimeType(family="date", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if "timestamp" in normalized or normalized in {"time", "timetz"}:
        return RuntimeType(family="datetime", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized in {"json", "jsonb"}:
        return RuntimeType(family="json", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    return RuntimeType(family="unknown", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect), source=type_name)


def parse_clickhouse_type(type_name: str) -> RuntimeType:
    stripped = type_name.strip()
    if not stripped:
        return UNKNOWN_RUNTIME_TYPE

    wrapper = _parse_wrapper(stripped, "Nullable")
    if wrapper is not None:
        return parse_clickhouse_type(wrapper).with_nullable(True)

    wrapper = _parse_wrapper(stripped, "LowCardinality")
    if wrapper is not None:
        return dataclasses.replace(parse_clickhouse_type(wrapper), dialect="clickhouse")

    wrapper = _parse_wrapper(stripped, "Array")
    if wrapper is not None:
        return RuntimeType(
            family="array",
            nullable=False,
            dialect="clickhouse",
            item_type=parse_clickhouse_type(wrapper),
            source=stripped,
        )

    wrapper = _parse_wrapper(stripped, "Map")
    if wrapper is not None:
        parts = _split_type_args(wrapper)
        if len(parts) == 2:
            return RuntimeType(
                family="map",
                nullable=False,
                dialect="clickhouse",
                key_type=parse_clickhouse_type(parts[0]),
                value_type=parse_clickhouse_type(parts[1]),
                source=stripped,
            )

    wrapper = _parse_wrapper(stripped, "Tuple")
    if wrapper is not None:
        item_types: list[RuntimeType] = []
        field_names: list[Optional[str]] = []
        for part in _split_type_args(wrapper):
            field_name, field_type = _split_tuple_field(part)
            field_names.append(field_name)
            item_types.append(parse_clickhouse_type(field_type))
        return RuntimeType(
            family="tuple",
            nullable=False,
            dialect="clickhouse",
            item_types=tuple(item_types),
            field_names=tuple(field_names),
            source=stripped,
        )

    wrapper = _parse_wrapper(stripped, "AggregateFunction") or _parse_wrapper(stripped, "SimpleAggregateFunction")
    if wrapper is not None:
        parts = _split_type_args(wrapper)
        wrapped_type = parse_clickhouse_type(parts[-1]) if parts else UNKNOWN_RUNTIME_TYPE
        return RuntimeType(
            family="aggregate_state",
            nullable=False,
            dialect="clickhouse",
            wrapped_type=wrapped_type,
            source=stripped,
        )

    integer_match = _INTEGER_RE.match(stripped)
    if integer_match:
        return RuntimeType(
            family="integer",
            nullable=False,
            dialect="clickhouse",
            signed=not integer_match.group(1).lower().startswith("u"),
            bits=int(integer_match.group(2)),
            source=stripped,
        )

    float_match = _FLOAT_RE.match(stripped)
    if float_match:
        return RuntimeType(
            family="float",
            nullable=False,
            dialect="clickhouse",
            bits=int(float_match.group(1)),
            source=stripped,
        )

    decimal_name = stripped.split("(", 1)[0]
    if _DECIMAL_RE.match(decimal_name):
        precision: Optional[int] = None
        scale: Optional[int] = None
        wrapper = _parse_parenthesized(stripped)
        if wrapper is not None:
            parts = _split_type_args(wrapper)
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                precision = int(parts[0])
                scale = int(parts[1])
        return RuntimeType(
            family="decimal",
            nullable=False,
            dialect="clickhouse",
            precision=precision,
            scale=scale,
            source=stripped,
        )

    normalized = stripped.lower()
    if normalized.startswith("datetime64"):
        parts = _split_type_args(_parse_parenthesized(stripped) or "")
        precision = int(parts[0]) if parts and parts[0].isdigit() else None
        timezone = _strip_quotes(parts[1]) if len(parts) > 1 else None
        return RuntimeType(
            family="datetime",
            nullable=False,
            dialect="clickhouse",
            precision=precision,
            timezone=timezone,
            source=stripped,
        )

    if normalized.startswith("datetime"):
        parts = _split_type_args(_parse_parenthesized(stripped) or "")
        timezone = _strip_quotes(parts[0]) if parts else None
        return RuntimeType(family="datetime", nullable=False, dialect="clickhouse", timezone=timezone, source=stripped)

    if normalized in {"string"}:
        return RuntimeType(family="string", nullable=False, dialect="clickhouse", source=stripped)
    if normalized.startswith("fixedstring"):
        parts = _split_type_args(_parse_parenthesized(stripped) or "")
        bits = int(parts[0]) if parts and parts[0].isdigit() else None
        return RuntimeType(family="fixed_string", nullable=False, dialect="clickhouse", bits=bits, source=stripped)
    if normalized in {"bool", "boolean"}:
        return RuntimeType(family="boolean", nullable=False, dialect="clickhouse", source=stripped)
    if normalized == "date" or normalized == "date32":
        return RuntimeType(family="date", nullable=False, dialect="clickhouse", source=stripped)
    if normalized == "uuid":
        return RuntimeType(family="uuid", nullable=False, dialect="clickhouse", source=stripped)
    if normalized in {"json", "object('json')"}:
        return RuntimeType(family="json", nullable=False, dialect="clickhouse", source=stripped)
    if normalized.startswith("enum"):
        return RuntimeType(family="enum", nullable=False, dialect="clickhouse", source=stripped)
    return RuntimeType(family="unknown", nullable=True, dialect="clickhouse", source=stripped)


def least_common_supertype(types: list[ast.ConstantType], dialect: HogQLDialect = "clickhouse") -> ast.ConstantType:
    if not types:
        return ast.UnknownType()
    runtime_types = [runtime_type_from_constant_type(type_) for type_ in types]
    return constant_type_from_runtime_type(least_common_runtime_type(runtime_types, dialect=dialect))


def least_common_runtime_type(runtime_types: list[RuntimeType], dialect: HogQLDialect = "clickhouse") -> RuntimeType:
    known_types = [type_ for type_ in runtime_types if type_.family != "unknown"]
    nullable = any(type_.nullable for type_ in runtime_types)
    if not known_types:
        return UNKNOWN_RUNTIME_TYPE.with_nullable(nullable)
    if len(known_types) == 1:
        return known_types[0].with_nullable(nullable)

    families = {type_.family for type_ in known_types}
    if families <= {"integer", "boolean"}:
        bits = max((type_.bits or 64) for type_ in known_types if type_.family == "integer") if known_types else 64
        signed = any(type_.signed is not False for type_ in known_types if type_.family == "integer")
        return RuntimeType(
            family="integer", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect), signed=signed, bits=bits
        )
    if families <= {"integer", "boolean", "float"}:
        return FLOAT_RUNTIME_TYPE.with_nullable(nullable)
    if families <= {"integer", "boolean", "decimal"}:
        return RuntimeType(family="decimal", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if families <= {"integer", "boolean", "float", "decimal"}:
        return FLOAT_RUNTIME_TYPE.with_nullable(nullable)
    if families <= {"date", "datetime"}:
        return (
            DATETIME_RUNTIME_TYPE.with_nullable(nullable)
            if "datetime" in families
            else DATE_RUNTIME_TYPE.with_nullable(nullable)
        )
    if families == {"string"} or families <= {"string", "fixed_string", "enum", "uuid"}:
        return STRING_RUNTIME_TYPE.with_nullable(nullable)
    if families == {"json"}:
        return RuntimeType(family="json", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if families == {"array"}:
        item_runtime_types = [
            type_.item_type if type_.item_type is not None else UNKNOWN_RUNTIME_TYPE for type_ in known_types
        ]
        return RuntimeType(
            family="array",
            nullable=nullable,
            dialect=cast(RuntimeTypeDialect, dialect),
            item_type=least_common_runtime_type(item_runtime_types, dialect=dialect),
        )
    if families == {"tuple"} and _same_tuple_width(known_types):
        width = len(known_types[0].item_types)
        item_types = tuple(
            least_common_runtime_type([type_.item_types[index] for type_ in known_types], dialect=dialect)
            for index in range(width)
        )
        return RuntimeType(
            family="tuple", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect), item_types=item_types
        )
    return UNKNOWN_RUNTIME_TYPE.with_nullable(nullable)


def comparison_compatibility(
    left_type: ast.ConstantType, right_type: ast.ConstantType, dialect: HogQLDialect = "clickhouse"
) -> ComparisonCompatibility:
    left = runtime_type_from_constant_type(left_type)
    right = runtime_type_from_constant_type(right_type)
    if left.family == "unknown" or right.family == "unknown":
        return ComparisonCompatibility.UNKNOWN
    if left.family == right.family:
        if left.family == "array":
            if left.item_type is None or right.item_type is None:
                return ComparisonCompatibility.UNKNOWN
            return comparison_compatibility(
                constant_type_from_runtime_type(left.item_type),
                constant_type_from_runtime_type(right.item_type),
                dialect=dialect,
            )
        return ComparisonCompatibility.DEFINITELY_COMPATIBLE
    families = {left.family, right.family}
    if families <= {"integer", "float", "decimal", "boolean"}:
        return ComparisonCompatibility.CHEAP_CAST
    if families <= {"date", "datetime"}:
        return ComparisonCompatibility.CHEAP_CAST
    if "string" in families and (families & {"date", "datetime", "integer", "float", "decimal", "uuid"}):
        return ComparisonCompatibility.EXPENSIVE_CAST
    return ComparisonCompatibility.INCOMPATIBLE


@dataclass(frozen=True, slots=True)
class FunctionTypeInference:
    return_type: ast.ConstantType
    source: Literal["generic", "legacy_signature", "unknown"]
    reason: str
    precise: bool = False


def infer_function_return_type(
    name: str,
    arg_types: list[ast.ConstantType],
    args: Optional[list[ast.Expr]] = None,
    meta: Optional[HogQLFunctionMeta] = None,
    dialect: HogQLDialect = "clickhouse",
) -> FunctionTypeInference:
    normalized_name = name.lower()
    generic_type = _infer_generic_function_type(normalized_name, arg_types, args=args, dialect=dialect)
    if generic_type is not None:
        return FunctionTypeInference(
            return_type=generic_type,
            source="generic",
            reason=f"{name} matched generic type inference",
            precise=not isinstance(generic_type, ast.UnknownType),
        )

    if meta is not None and meta.signatures is not None:
        for sig_arg_types, sig_return_type in meta.signatures:
            if sig_arg_types is None or _compare_legacy_types(arg_types, sig_arg_types, args=args):
                return FunctionTypeInference(
                    return_type=dataclasses.replace(sig_return_type),
                    source="legacy_signature",
                    reason=f"{name} matched legacy signature",
                    precise=not isinstance(sig_return_type, ast.UnknownType),
                )

    return FunctionTypeInference(
        return_type=ast.UnknownType(),
        source="unknown",
        reason=f"{name} has no matching type signature",
        precise=False,
    )


def infer_cast_constant_type(type_name: str, input_type: ast.ConstantType, dialect: HogQLDialect) -> ast.ConstantType:
    target_type = parse_sql_runtime_type(type_name, dialect=dialect)
    if target_type.family == "unknown":
        return ast.UnknownType(nullable=True)
    if target_type.nullable:
        return constant_type_from_runtime_type(target_type)
    return constant_type_from_runtime_type(target_type.with_nullable(input_type.nullable))


def infer_try_cast_constant_type(type_name: str, dialect: HogQLDialect) -> ast.ConstantType:
    target_type = parse_sql_runtime_type(type_name, dialect=dialect)
    if target_type.family == "unknown":
        return ast.UnknownType(nullable=True)
    return constant_type_from_runtime_type(target_type.with_nullable(True))


def infer_array_constant_type(items: list[ast.ConstantType], dialect: HogQLDialect = "clickhouse") -> ast.ArrayType:
    item_type = least_common_supertype(items, dialect=dialect) if items else ast.UnknownType()
    return ast.ArrayType(nullable=False, item_type=item_type)


def infer_array_access_constant_type(array_type: ast.ConstantType) -> ast.ConstantType:
    if isinstance(array_type, ast.ArrayType):
        return dataclasses.replace(array_type.item_type, nullable=array_type.nullable or array_type.item_type.nullable)
    if isinstance(array_type, ast.StringArrayType):
        return ast.StringType(nullable=True)
    return ast.UnknownType()


def infer_array_slice_constant_type(array_type: ast.ConstantType) -> ast.ConstantType:
    if isinstance(array_type, ast.ArrayType):
        return dataclasses.replace(array_type)
    if isinstance(array_type, ast.StringArrayType):
        return ast.ArrayType(nullable=array_type.nullable, item_type=ast.StringType(nullable=False))
    return ast.UnknownType()


def infer_tuple_access_constant_type(tuple_type: ast.ConstantType, index: int) -> ast.ConstantType:
    if not isinstance(tuple_type, ast.TupleType):
        return ast.UnknownType()
    zero_based_index = index - 1
    if zero_based_index < 0 or zero_based_index >= len(tuple_type.item_types):
        return ast.UnknownType()
    item_type = tuple_type.item_types[zero_based_index]
    return dataclasses.replace(item_type, nullable=tuple_type.nullable or item_type.nullable)


def _infer_generic_function_type(
    normalized_name: str,
    arg_types: list[ast.ConstantType],
    args: Optional[list[ast.Expr]],
    dialect: HogQLDialect,
) -> ast.ConstantType | None:
    if normalized_name in {
        "equals",
        "notequals",
        "less",
        "greater",
        "lessorequals",
        "greaterorequals",
        "in",
        "notin",
        "like",
        "ilike",
        "notlike",
        "notilike",
        "isnull",
        "isnotnull",
        "isempty",
        "isnotempty",
        "has",
        "hasall",
        "hasany",
        "hassubstr",
        "mapcontains",
        "mapcontainskeylike",
        "isfinite",
        "isinfinite",
        "isnan",
    }:
        return ast.BooleanType(nullable=False)

    if normalized_name in {"and", "or", "xor", "not"}:
        return ast.BooleanType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in {"if", "ifnull"}:
        return least_common_supertype(arg_types[1:], dialect=dialect) if len(arg_types) > 1 else ast.UnknownType()

    if normalized_name == "multiif":
        if len(arg_types) < 3:
            return ast.UnknownType()
        return least_common_supertype([*arg_types[1::2], arg_types[-1]], dialect=dialect)

    if normalized_name in {"coalesce", "least", "greatest"}:
        return least_common_supertype(arg_types, dialect=dialect)

    if normalized_name == "nullif" and arg_types:
        result = dataclasses.replace(arg_types[0])
        result.nullable = True
        return result

    if normalized_name in {"assumenotnull", "tonullable"} and arg_types:
        result = dataclasses.replace(arg_types[0])
        result.nullable = normalized_name == "tonullable"
        return result

    if normalized_name == "tostring" or normalized_name == "totypename" or normalized_name.endswith("tostring"):
        return ast.StringType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if (
        normalized_name in {"toint", "tointorzero"}
        or normalized_name.startswith("_toint")
        or normalized_name.startswith("_touint")
    ):
        return ast.IntegerType(nullable=_conversion_nullable(normalized_name, arg_types))

    if normalized_name in {"tofloat", "tofloatorzero", "tofloatordefault"}:
        return ast.FloatType(nullable=_conversion_nullable(normalized_name, arg_types))

    if normalized_name == "todecimal":
        return ast.DecimalType(nullable=True)

    if normalized_name in {"todate", "to_date", "_todate"}:
        return ast.DateType(nullable=_conversion_nullable(normalized_name, arg_types))

    if normalized_name in {"todatetime", "todatetime64", "todatetimeus", "parsedatetime", "parsedatetimebesteffort"}:
        return ast.DateTimeType(nullable=_conversion_nullable(normalized_name, arg_types))

    if normalized_name.startswith("tointerval"):
        return ast.IntervalType(nullable=False)

    if normalized_name in {"touuid", "touuidordefault", "reinterpretasuuid"}:
        return ast.UUIDType(nullable=_conversion_nullable(normalized_name, arg_types))

    if normalized_name == "tobool":
        return ast.BooleanType(nullable=_conversion_nullable(normalized_name, arg_types))

    if normalized_name == "array":
        return infer_array_constant_type(arg_types, dialect=dialect)

    if normalized_name in {"arrayconcat", "arrayzip"}:
        return _infer_array_concat_type(arg_types, dialect=dialect)

    if (
        normalized_name
        in {
            "arrayslice",
            "arrayreverse",
            "arraydistinct",
            "arraysort",
            "arrayreversesort",
            "arraypopback",
            "arraypopfront",
            "arraycompact",
        }
        and arg_types
    ):
        return infer_array_slice_constant_type(arg_types[0])

    if normalized_name in {"arrayelement", "arrayjoin", "arrayfirst", "arraylast"} and arg_types:
        return infer_array_access_constant_type(
            arg_types[-1] if normalized_name in {"arrayfirst", "arraylast"} else arg_types[0]
        )

    if normalized_name in {"arrayenumerate", "arrayenumerateuniq", "arrayenumeratedense", "range"}:
        return ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False))

    if normalized_name in {"arraymap", "arrayfilter"}:
        return _infer_higher_order_array_type(arg_types, args=args, dialect=dialect)

    if normalized_name in {"arrayexists", "arrayall"}:
        return ast.BooleanType(nullable=False)

    if normalized_name in {"arraysum", "arrayavg", "arraymin", "arraymax"} and arg_types:
        item_type = infer_array_access_constant_type(arg_types[-1])
        if normalized_name == "arrayavg":
            return ast.FloatType(nullable=item_type.nullable)
        return item_type

    if normalized_name == "tuple":
        return ast.TupleType(nullable=False, item_types=[dataclasses.replace(arg_type) for arg_type in arg_types])

    if normalized_name == "tupleelement" and len(arg_types) >= 2:
        index = _constant_int(args[1]) if args and len(args) > 1 else None
        if index is not None:
            return infer_tuple_access_constant_type(arg_types[0], index)
        return ast.UnknownType()

    if normalized_name in {"count", "countif", "countdistinct", "uniq", "uniqexact", "uniqhll12", "uniqtheta"}:
        return ast.IntegerType(nullable=False)

    if normalized_name in {"sum", "sumif"} and arg_types:
        input_type = arg_types[0]
        if isinstance(input_type, ast.FloatType):
            return ast.FloatType(nullable=input_type.nullable)
        if isinstance(input_type, ast.DecimalType):
            return ast.DecimalType(nullable=input_type.nullable)
        return ast.IntegerType(nullable=input_type.nullable)

    if normalized_name in {"avg", "avgif", "median", "stddevpop", "stddevsamp", "varpop", "varsamp"}:
        return ast.FloatType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in {"min", "minif", "max", "maxif", "any", "anyif", "anylast", "anylastif"} and arg_types:
        return dataclasses.replace(arg_types[0])

    if (
        normalized_name in {"grouparray", "array_agg", "groupuniqarray", "grouparrayif", "groupuniqarrayif"}
        and arg_types
    ):
        return ast.ArrayType(nullable=False, item_type=dataclasses.replace(arg_types[0]))

    if normalized_name.endswith("state"):
        return ast.UnknownType(nullable=False)

    if normalized_name.endswith("merge") or normalized_name.endswith("mergeif"):
        return ast.UnknownType(nullable=False)

    return None


def _compare_legacy_types(
    arg_types: list[ast.ConstantType],
    sig_arg_types: tuple[ast.ConstantType, ...],
    args: Optional[list[ast.Expr]] = None,
) -> bool:
    if len(arg_types) != len(sig_arg_types):
        return False

    for index, (arg_type, sig_arg_type) in enumerate(zip(arg_types, sig_arg_types)):
        if isinstance(sig_arg_type, ast.UnknownType):
            continue
        if isinstance(sig_arg_type, ast.StringLiteralType):
            if not isinstance(arg_type, ast.StringType):
                return False
            if args is None or index >= len(args):
                return False
            arg_node = args[index]
            if not isinstance(arg_node, ast.Constant) or not isinstance(arg_node.value, str):
                return False
            if arg_node.value.lower() not in sig_arg_type.values:
                return False
            continue
        if not isinstance(arg_type, sig_arg_type.__class__):
            return False
    return True


def _conversion_nullable(normalized_name: str, arg_types: list[ast.ConstantType]) -> bool:
    if normalized_name.endswith("orzero") or normalized_name.endswith("ordefault"):
        return False
    return any(arg_type.nullable for arg_type in arg_types) or normalized_name in {
        "toint",
        "tofloat",
        "touuid",
        "todecimal",
        "parsedatetime",
        "parsedatetimebesteffort",
    }


def _infer_array_concat_type(arg_types: list[ast.ConstantType], dialect: HogQLDialect) -> ast.ArrayType:
    item_types: list[ast.ConstantType] = []
    nullable = False
    for arg_type in arg_types:
        nullable = nullable or arg_type.nullable
        if isinstance(arg_type, ast.ArrayType):
            item_types.append(arg_type.item_type)
        elif isinstance(arg_type, ast.StringArrayType):
            item_types.append(ast.StringType(nullable=False))
        else:
            item_types.append(ast.UnknownType())
    return ast.ArrayType(nullable=nullable, item_type=least_common_supertype(item_types, dialect=dialect))


def _infer_higher_order_array_type(
    arg_types: list[ast.ConstantType], args: Optional[list[ast.Expr]], dialect: HogQLDialect
) -> ast.ConstantType:
    array_arg_types = arg_types[1:] if args and args and isinstance(args[0], ast.Lambda) else arg_types
    if not array_arg_types:
        return ast.UnknownType()
    first_array_type = array_arg_types[0]
    if isinstance(first_array_type, ast.ArrayType):
        return ast.ArrayType(
            nullable=first_array_type.nullable, item_type=dataclasses.replace(first_array_type.item_type)
        )
    if isinstance(first_array_type, ast.StringArrayType):
        return ast.ArrayType(nullable=first_array_type.nullable, item_type=ast.StringType(nullable=False))
    return ast.ArrayType(nullable=True, item_type=least_common_supertype(array_arg_types, dialect=dialect))


def _constant_int(expr: ast.Expr) -> Optional[int]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
        return expr.value
    return None


def _same_tuple_width(runtime_types: list[RuntimeType]) -> bool:
    if not runtime_types:
        return False
    width = len(runtime_types[0].item_types)
    return all(len(type_.item_types) == width for type_ in runtime_types)


def _parse_wrapper(type_name: str, wrapper_name: str) -> Optional[str]:
    prefix = f"{wrapper_name}("
    if not type_name.lower().startswith(prefix.lower()) or not type_name.endswith(")"):
        return None
    return type_name[len(prefix) : -1].strip()


def _parse_parenthesized(type_name: str) -> Optional[str]:
    opening = type_name.find("(")
    if opening == -1 or not type_name.endswith(")"):
        return None
    return type_name[opening + 1 : -1].strip()


def _split_type_args(value: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth = 0
    quote: Optional[str] = None
    escape = False
    for char in value:
        if quote is not None:
            current.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
            current.append(char)
            continue
        if char == ")":
            depth -= 1
            current.append(char)
            continue
        if char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        args.append("".join(current).strip())
    return args


def _split_tuple_field(value: str) -> tuple[Optional[str], str]:
    depth = 0
    quote: Optional[str] = None
    for index, char in enumerate(value):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            continue
        if char == " " and depth == 0:
            candidate = _strip_quotes(value[:index].strip())
            rest = value[index + 1 :].strip()
            if candidate and rest:
                return candidate, rest
    return None, value


def _strip_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"', "`"}:
        return stripped[1:-1]
    return stripped
