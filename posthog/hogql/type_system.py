from __future__ import annotations

import re
import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
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
type RuntimeTypeDialect = Literal["common", "clickhouse", "postgres", "duckdb", "mysql"]


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
    low_cardinality: bool = False
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
    # Mirrors ast.UnknownType.unanalyzable: an unknown that could be any type (poisons unification)
    # rather than a vacuous unknown from a null literal / empty container (absorbed).
    unanalyzable: bool = False

    def non_nullable(self) -> RuntimeType:
        return dataclasses.replace(self, nullable=False)

    def with_nullable(self, nullable: bool) -> RuntimeType:
        return dataclasses.replace(self, nullable=nullable)

    def display(self) -> str:
        inner = self._display_inner()
        if self.low_cardinality:
            inner = f"LowCardinality({inner})"
        return f"Nullable({inner})" if self.nullable else inner

    def debug_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "family": self.family,
            "nullable": self.nullable,
            "dialect": self.dialect,
        }
        if self.low_cardinality:
            data["low_cardinality"] = True
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
            item_display = self.item_type.display() if self.item_type is not None else "Unknown"
            return f"Array({item_display})"
        if self.family == "tuple":
            parts = []
            for index, tuple_item_type in enumerate(self.item_types):
                name = self.field_names[index] if index < len(self.field_names) else None
                parts.append(f"{name} {tuple_item_type.display()}" if name else tuple_item_type.display())
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
ANY_RUNTIME_TYPE = RuntimeType(family="unknown", unanalyzable=True)
STRING_RUNTIME_TYPE = RuntimeType(family="string")
BOOLEAN_RUNTIME_TYPE = RuntimeType(family="boolean")
INTEGER_RUNTIME_TYPE = RuntimeType(family="integer", signed=True, bits=64)
FLOAT_RUNTIME_TYPE = RuntimeType(family="float", bits=64)
DATE_RUNTIME_TYPE = RuntimeType(family="date")
DATETIME_RUNTIME_TYPE = RuntimeType(family="datetime")


_INTEGER_RE = re.compile(r"^(U?Int)(8|16|32|64|128|256)$", re.IGNORECASE)
_FLOAT_RE = re.compile(r"^Float(32|64)$", re.IGNORECASE)
_DECIMAL_RE = re.compile(r"^Decimal(?:32|64|128|256)?$", re.IGNORECASE)

_STRING_RESULT_FUNCTIONS = frozenset(
    {
        "appendtrailingcharifabsent",
        "base58decode",
        "base58encode",
        "base64decode",
        "base64encode",
        "concat",
        "concatwithseparator",
        "convertcharset",
        "decodexmlcomponent",
        "encodexmlcomponent",
        "extract",
        "extracttextfromhtml",
        "format",
        "hex",
        "leftpad",
        "leftpadutf8",
        "lower",
        "lowerutf8",
        "regexpextract",
        "regexpquotemeta",
        "repeat",
        "replace",
        "replaceall",
        "replaceone",
        "replaceregexpall",
        "replaceregexpone",
        "reverseutf8",
        "rightpad",
        "rightpadutf8",
        "substring",
        "substringutf8",
        "tostring",
        "tojsonstring",
        "trybase58decode",
        "trybase64decode",
        "unhex",
        "upper",
        "upperutf8",
    }
)

_STRING_ARRAY_RESULT_FUNCTIONS = frozenset(
    {
        "alphatokens",
        "extractall",
        "ngrams",
        "splitbychar",
        "splitbynonalpha",
        "splitbyregexp",
        "splitbystring",
        "splitbywhitespace",
        "tokens",
    }
)

_URL_STRING_RESULT_FUNCTIONS = frozenset(
    {
        "cutfragment",
        "cutquerystring",
        "cutquerystringandfragment",
        "cuttofirstsignificantsubdomain",
        "cuttofirstsignificantsubdomainwithwww",
        "cuturlparameter",
        "cutwww",
        "decodeurlcomponent",
        "decodeurlformcomponent",
        "domain",
        "domainwithoutwww",
        "encodeurlcomponent",
        "encodeurlformcomponent",
        "extracturlparameter",
        "firstsignificantsubdomain",
        "fragment",
        "netloc",
        "path",
        "pathfull",
        "protocol",
        "querystring",
        "querystringandfragment",
        "topleveldomain",
    }
)

_URL_STRING_ARRAY_RESULT_FUNCTIONS = frozenset(
    {
        "extracturlparameternames",
        "extracturlparameters",
        "urlhierarchy",
        "urlpathhierarchy",
    }
)

_INTEGER_RESULT_FUNCTIONS = frozenset({"port"})
_DATE_PART_RESULT_FUNCTIONS = frozenset(
    {
        "toyear",
        "toquarter",
        "tomonth",
        "todayofyear",
        "todayofmonth",
        "todayofweek",
        "tohour",
        "tominute",
        "tosecond",
        "tounixtimestamp",
        "tounixtimestamp64milli",
        "toyyyymm",
        "toyyyymmdd",
        "toyyyymmddhhmmss",
        "toisoyear",
        "toisoweek",
        "toweek",
        "toyearweek",
        "timezoneoffset",
        "datediff",
        "date_diff",
        "rownumberinblock",
        "rownumberinallblocks",
    }
)
_DATE_STRING_RESULT_FUNCTIONS = frozenset({"timezoneof", "formatdatetime", "datename", "monthname"})
# Day-and-above granularity: ClickHouse keeps a Date argument as a Date.
_DATE_ARITHMETIC_FIRST_ARG_RESULT_FUNCTIONS = frozenset(
    {
        "adddays",
        "addweeks",
        "addmonths",
        "addquarters",
        "addyears",
        "subtractdays",
        "subtractweeks",
        "subtractmonths",
        "subtractquarters",
        "subtractyears",
    }
)

# Sub-day granularity: ClickHouse promotes a Date argument to DateTime.
_SUB_DAY_DATE_ARITHMETIC_FUNCTIONS = frozenset(
    {
        "addnanoseconds",
        "addmicroseconds",
        "addmilliseconds",
        "addseconds",
        "addminutes",
        "addhours",
        "subtractnanoseconds",
        "subtractmicroseconds",
        "subtractmilliseconds",
        "subtractseconds",
        "subtractminutes",
        "subtracthours",
    }
)
_READABLE_STRING_RESULT_FUNCTIONS = frozenset(
    {
        "bar",
        "formatreadabledecimalsize",
        "formatreadablesize",
        "formatreadablequantity",
        "formatreadabletimedelta",
    }
)
_BITMAP_INTEGER_RESULT_FUNCTIONS = frozenset(
    {
        "bitmapcardinality",
        "bitmapmin",
        "bitmapmax",
        "bitmapandcardinality",
        "bitmaporcardinality",
        "bitmapxorcardinality",
        "bitmapandnotcardinality",
    }
)
_BITMAP_BOOLEAN_RESULT_FUNCTIONS = frozenset({"bitmapcontains", "bitmaphasany", "bitmaphasall"})
_BITMAP_RESULT_FUNCTIONS = frozenset(
    {
        "bitmapbuild",
        "bitmapsubsetinrange",
        "bitmapsubsetlimit",
        "subbitmap",
        "bitmaptransform",
        "bitmapand",
        "bitmapor",
        "bitmapxor",
        "bitmapandnot",
    }
)
_VECTOR_FLOAT_RESULT_FUNCTIONS = frozenset(
    {
        "l1norm",
        "l2norm",
        "linfnorm",
        "lpnorm",
        "l1distance",
        "l2distance",
        "linfdistance",
        "lpdistance",
        "cosinedistance",
    }
)
_VECTOR_ARRAY_RESULT_FUNCTIONS = frozenset({"l1normalize", "l2normalize", "linfnormalize", "lpnormalize"})


def runtime_type_from_constant_type(constant_type: ast.ConstantType) -> RuntimeType:
    nullable = constant_type.nullable
    if isinstance(constant_type, ast.UnknownType):
        base = ANY_RUNTIME_TYPE if constant_type.unanalyzable else UNKNOWN_RUNTIME_TYPE
        return base.with_nullable(nullable)
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
            field_names=tuple(constant_type.field_names),
        )
    if isinstance(constant_type, ast.AggregateStateType):
        return RuntimeType(
            family="aggregate_state",
            nullable=nullable,
            wrapped_type=runtime_type_from_constant_type(constant_type.wrapped_type),
        )
    if isinstance(constant_type, ast.MapType):
        return RuntimeType(
            family="map",
            nullable=nullable,
            key_type=runtime_type_from_constant_type(constant_type.key_type),
            value_type=runtime_type_from_constant_type(constant_type.value_type),
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
            field_names=list(runtime_type.field_names),
        )
    if runtime_type.family == "aggregate_state":
        return ast.AggregateStateType(
            nullable=nullable,
            wrapped_type=constant_type_from_runtime_type(runtime_type.wrapped_type or UNKNOWN_RUNTIME_TYPE),
        )
    if runtime_type.family == "map":
        return ast.MapType(
            nullable=nullable,
            key_type=constant_type_from_runtime_type(runtime_type.key_type or UNKNOWN_RUNTIME_TYPE),
            value_type=constant_type_from_runtime_type(runtime_type.value_type or UNKNOWN_RUNTIME_TYPE),
        )
    return ast.UnknownType(nullable=nullable, unanalyzable=runtime_type.unanalyzable)


def runtime_type_from_database_field(database_field: DatabaseField) -> RuntimeType:
    return runtime_type_from_constant_type(database_field.get_constant_type())


@lru_cache(maxsize=1024)
def normalized_runtime_type(runtime_type: RuntimeType) -> RuntimeType:
    """Erase display-only fields (source text, LowCardinality wrapper) recursively, so two
    spellings of the same type (whitespace, quoting, LC encoding) compare equal."""
    return dataclasses.replace(
        runtime_type,
        source=None,
        low_cardinality=False,
        item_type=normalized_runtime_type(runtime_type.item_type) if runtime_type.item_type else None,
        item_types=tuple(normalized_runtime_type(item) for item in runtime_type.item_types),
        key_type=normalized_runtime_type(runtime_type.key_type) if runtime_type.key_type else None,
        value_type=normalized_runtime_type(runtime_type.value_type) if runtime_type.value_type else None,
        wrapped_type=normalized_runtime_type(runtime_type.wrapped_type) if runtime_type.wrapped_type else None,
    )


def parse_sql_runtime_type(type_name: str, dialect: HogQLDialect = "clickhouse") -> RuntimeType:
    if dialect == "clickhouse":
        return parse_clickhouse_type(type_name)
    normalized = type_name.strip().lower()
    nullable = False
    if normalized in {"boolean", "bool"}:
        return RuntimeType(family="boolean", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized in {"integer", "int", "bigint", "smallint", "tinyint", "mediumint", "signed", "unsigned"}:
        return RuntimeType(family="integer", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized in {"real", "double precision", "double", "float"}:
        return RuntimeType(family="float", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized.startswith("decimal") or normalized.startswith("numeric"):
        return RuntimeType(family="decimal", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized in {
        "text",
        "varchar",
        "character varying",
        "char",
        "character",
        "uuid",
        "tinytext",
        "mediumtext",
        "longtext",
    }:
        family: RuntimeTypeFamily = "uuid" if normalized == "uuid" else "string"
        return RuntimeType(family=family, nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized == "date":
        return RuntimeType(family="date", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if "timestamp" in normalized or normalized in {"time", "timetz", "datetime"}:
        return RuntimeType(family="datetime", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    if normalized in {"json", "jsonb"}:
        return RuntimeType(family="json", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect))
    return RuntimeType(family="unknown", nullable=nullable, dialect=cast(RuntimeTypeDialect, dialect), source=type_name)


@lru_cache(maxsize=1024)
def parse_clickhouse_type(type_name: str) -> RuntimeType:
    stripped = type_name.strip()
    if not stripped:
        return UNKNOWN_RUNTIME_TYPE

    wrapper = _parse_wrapper(stripped, "Nullable")
    if wrapper is not None:
        return parse_clickhouse_type(wrapper).with_nullable(True)

    wrapper = _parse_wrapper(stripped, "LowCardinality")
    if wrapper is not None:
        return dataclasses.replace(
            parse_clickhouse_type(wrapper),
            dialect="clickhouse",
            low_cardinality=True,
            source=stripped,
        )

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

    normalized = stripped.lower()
    if normalized in {"int", "integer", "bigint"}:
        return RuntimeType(
            family="integer", nullable=False, dialect="clickhouse", signed=True, bits=64, source=stripped
        )
    if normalized in {"float", "double", "double precision", "real"}:
        return RuntimeType(family="float", nullable=False, dialect="clickhouse", bits=64, source=stripped)
    if normalized in {"text", "varchar", "char", "string"}:
        return RuntimeType(family="string", nullable=False, dialect="clickhouse", source=stripped)
    if normalized in {
        "datetime",
        "timestamp",
        "timestamptz",
        "timestamp with time zone",
        "timestamp with local time zone",
    }:
        return RuntimeType(family="datetime", nullable=False, dialect="clickhouse", source=stripped)

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


# Scalar constant types whose runtime type is fully determined by (class, nullable) — used to
# dedupe before unification so large homogeneous literal arrays don't allocate per element.
# Only families where unifying N identical types equals unifying one belong here; UUIDType and
# IntervalType don't (a lone uuid keeps its family, but several unify to string via the subset rule).
_SIMPLE_CONSTANT_TYPE_CLASSES = frozenset(
    {
        ast.BooleanType,
        ast.IntegerType,
        ast.FloatType,
        ast.DecimalType,
        ast.StringType,
        ast.StringJSONType,
        ast.StringArrayType,
        ast.DateType,
        ast.DateTimeType,
    }
)


def least_common_supertype(types: Sequence[ast.ConstantType], dialect: HogQLDialect = "clickhouse") -> ast.ConstantType:
    if not types:
        return ast.UnknownType()
    runtime_types: list[RuntimeType] = []
    seen_simple: set[tuple[type, bool]] = set()
    for type_ in types:
        if type(type_) in _SIMPLE_CONSTANT_TYPE_CLASSES:
            key = (type(type_), type_.nullable)
            if key in seen_simple:
                continue
            seen_simple.add(key)
        runtime_types.append(runtime_type_from_constant_type(type_))
    return constant_type_from_runtime_type(least_common_runtime_type(runtime_types, dialect=dialect))


def least_common_runtime_type(runtime_types: list[RuntimeType], dialect: HogQLDialect = "clickhouse") -> RuntimeType:
    nullable = any(type_.nullable for type_ in runtime_types)
    # An unanalyzable branch could be any type, so it poisons the result; a vacuous unknown
    # (null literal / empty container) imposes no constraint and is dropped so a sibling can win.
    if any(type_.family == "unknown" and type_.unanalyzable for type_ in runtime_types):
        return ANY_RUNTIME_TYPE.with_nullable(nullable)
    known_types = [type_ for type_ in runtime_types if type_.family != "unknown"]
    if not known_types:
        return UNKNOWN_RUNTIME_TYPE.with_nullable(nullable)
    if len(known_types) == 1:
        return known_types[0].with_nullable(nullable)

    families = {type_.family for type_ in known_types}
    if families == {"boolean"}:
        return BOOLEAN_RUNTIME_TYPE.with_nullable(nullable)
    if families <= {"integer", "boolean"}:
        bits = max((type_.bits or 64) for type_ in known_types if type_.family == "integer")
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
    if families <= {"string", "fixed_string", "enum", "uuid"}:
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
            family="tuple",
            nullable=nullable,
            dialect=cast(RuntimeTypeDialect, dialect),
            item_types=item_types,
            field_names=_common_tuple_field_names(known_types),
        )
    if families == {"map"}:
        key_types = [type_.key_type or UNKNOWN_RUNTIME_TYPE for type_ in known_types]
        value_types = [type_.value_type or UNKNOWN_RUNTIME_TYPE for type_ in known_types]
        return RuntimeType(
            family="map",
            nullable=nullable,
            dialect=cast(RuntimeTypeDialect, dialect),
            key_type=least_common_runtime_type(key_types, dialect=dialect),
            value_type=least_common_runtime_type(value_types, dialect=dialect),
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
        from posthog.hogql.functions.core import (
            compare_types,  # noqa: PLC0415 — keeps the functions package (and its Django imports) off the type-system import path
        )

        for sig_arg_types, sig_return_type in meta.signatures:
            if sig_arg_types is None or compare_types(arg_types, sig_arg_types, args=args):
                # A signature that declares an unknown return can't determine the type, so it poisons
                # unification rather than being absorbed as a vacuous unknown.
                return_type: ast.ConstantType = (
                    ast.UnknownType(nullable=sig_return_type.nullable, unanalyzable=True)
                    if isinstance(sig_return_type, ast.UnknownType)
                    else dataclasses.replace(sig_return_type)
                )
                return FunctionTypeInference(
                    return_type=return_type,
                    source="legacy_signature",
                    reason=f"{name} matched legacy signature",
                    precise=not isinstance(sig_return_type, ast.UnknownType),
                )

    return FunctionTypeInference(
        return_type=ast.UnknownType(unanalyzable=True),
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
        # ClickHouse returns the item type's default value for out-of-bounds access on non-nullable arrays.
        return dataclasses.replace(array_type.item_type, nullable=array_type.nullable or array_type.item_type.nullable)
    if isinstance(array_type, ast.StringArrayType):
        return ast.StringType(nullable=True)
    if isinstance(array_type, ast.MapType):
        return dataclasses.replace(
            array_type.value_type, nullable=array_type.nullable or array_type.value_type.nullable
        )
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


def infer_tuple_name_access_constant_type(tuple_type: ast.ConstantType, field_name: str) -> ast.ConstantType:
    if not isinstance(tuple_type, ast.TupleType):
        return ast.UnknownType()
    try:
        index = tuple_type.field_names.index(field_name)
    except ValueError:
        return ast.UnknownType()
    if index >= len(tuple_type.item_types):
        return ast.UnknownType()
    item_type = tuple_type.item_types[index]
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

    if normalized_name == "if":
        return least_common_supertype(arg_types[1:], dialect=dialect) if len(arg_types) > 1 else ast.UnknownType()

    if normalized_name == "ifnull":
        return least_common_supertype(arg_types, dialect=dialect) if len(arg_types) > 1 else ast.UnknownType()

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

    if normalized_name in {"accuratecast", "accuratecastornull"}:
        return _infer_cast_function_type(
            arg_types=arg_types,
            args=args,
            dialect=dialect,
            nullable_on_failure=normalized_name == "accuratecastornull",
        )

    if normalized_name == "totypename" or normalized_name.endswith("tostring"):
        return ast.StringType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in _STRING_RESULT_FUNCTIONS or normalized_name in _URL_STRING_RESULT_FUNCTIONS:
        return ast.StringType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in _STRING_ARRAY_RESULT_FUNCTIONS or normalized_name in _URL_STRING_ARRAY_RESULT_FUNCTIONS:
        return ast.ArrayType(
            nullable=any(arg_type.nullable for arg_type in arg_types),
            item_type=ast.StringType(nullable=False),
        )

    if normalized_name in _INTEGER_RESULT_FUNCTIONS:
        return ast.IntegerType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in _DATE_PART_RESULT_FUNCTIONS:
        return ast.IntegerType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in _DATE_STRING_RESULT_FUNCTIONS or normalized_name in _READABLE_STRING_RESULT_FUNCTIONS:
        return ast.StringType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in {"fromunixtimestamp", "fromunixtimestamp64milli", "timeslot"}:
        return ast.DateTimeType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name == "timeslots":
        return ast.ArrayType(
            nullable=any(arg_type.nullable for arg_type in arg_types),
            item_type=ast.DateTimeType(nullable=False),
        )

    if normalized_name in {"dateadd", "datesub"} and arg_types:
        if len(arg_types) >= 3 and isinstance(arg_types[0], ast.StringType):
            return dataclasses.replace(arg_types[2])
        return dataclasses.replace(arg_types[0])

    if normalized_name in {"date_add", "date_subtract"} and arg_types:
        return dataclasses.replace(arg_types[0])

    if normalized_name in _DATE_ARITHMETIC_FIRST_ARG_RESULT_FUNCTIONS and arg_types:
        return dataclasses.replace(arg_types[0])

    if normalized_name in _SUB_DAY_DATE_ARITHMETIC_FUNCTIONS and arg_types:
        # ClickHouse promotes a Date argument to the datetime family (DateTime, or DateTime64 for
        # Date32 / sub-second granularity); a datetime argument stays in the datetime family. The
        # constant types are family-level (no precision), so promoting Date -> DateTimeType suffices.
        if isinstance(arg_types[0], ast.DateType):
            return ast.DateTimeType(nullable=arg_types[0].nullable)
        return dataclasses.replace(arg_types[0])

    if normalized_name in {"rank", "dense_rank", "row_number"}:
        return ast.IntegerType(nullable=False)

    if normalized_name in {"first_value", "last_value", "nth_value", "lag", "lead", "laginframe", "leadinframe"}:
        if arg_types:
            result = dataclasses.replace(arg_types[0])
            if normalized_name in {"lag", "lead", "laginframe", "leadinframe"}:
                result.nullable = True
            return result
        return ast.UnknownType()

    if normalized_name == "bitmaptoarray":
        return ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False))

    if normalized_name in _BITMAP_INTEGER_RESULT_FUNCTIONS:
        return ast.IntegerType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in _BITMAP_BOOLEAN_RESULT_FUNCTIONS:
        return ast.BooleanType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in _BITMAP_RESULT_FUNCTIONS:
        return ast.UnknownType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name.startswith("bit"):
        return ast.IntegerType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in _VECTOR_FLOAT_RESULT_FUNCTIONS:
        return ast.FloatType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in _VECTOR_ARRAY_RESULT_FUNCTIONS and arg_types:
        return dataclasses.replace(arg_types[0])

    if normalized_name == "jsonextract":
        return _infer_json_extract_type(arg_types=arg_types, args=args, dialect=dialect)

    if normalized_name in {"isvalidjson", "jsonhas", "jsonlength", "jsonarraylength"}:
        return ast.IntegerType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in {"jsontype", "json_value"}:
        return ast.StringType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in {"jsonextractuint", "jsonextractint"}:
        return ast.IntegerType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name == "jsonextractfloat":
        return ast.FloatType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name == "jsonextractbool":
        return ast.BooleanType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in {"jsonextractstring", "jsonextractraw"}:
        return ast.StringType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in {"jsonextractkeys", "jsonextractarrayraw"}:
        return ast.ArrayType(
            nullable=any(arg_type.nullable for arg_type in arg_types),
            item_type=ast.StringType(nullable=False),
        )

    if normalized_name == "jsonextractkeysandvalues":
        return _infer_json_extract_keys_and_values_type(arg_types=arg_types, args=args, dialect=dialect)

    if normalized_name == "jsonextractkeysandvaluesraw":
        return ast.ArrayType(
            nullable=any(arg_type.nullable for arg_type in arg_types),
            item_type=ast.TupleType(
                nullable=False,
                item_types=[ast.StringType(nullable=False), ast.StringType(nullable=False)],
            ),
        )

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

    if normalized_name in {"touuid", "touuidordefault"}:
        return ast.UUIDType(nullable=_conversion_nullable(normalized_name, arg_types))

    if normalized_name == "tobool":
        return ast.BooleanType(nullable=_conversion_nullable(normalized_name, arg_types))

    if normalized_name.startswith("reinterpretas"):
        return _infer_reinterpret_type(normalized_name, arg_types)

    if normalized_name == "array":
        return infer_array_constant_type(arg_types, dialect=dialect)

    if normalized_name == "map":
        return _infer_map_type(arg_types, dialect=dialect)

    if normalized_name == "mapfromarrays" and len(arg_types) >= 2:
        return _infer_map_from_arrays_type(arg_types, dialect=dialect)

    if normalized_name in {"mapkeys", "mapvalues"} and arg_types:
        return _infer_map_items_type(arg_types[0], keys=normalized_name == "mapkeys")

    if normalized_name in {"mapadd", "mapsubtract", "mapupdate"} and arg_types:
        map_types = [arg_type for arg_type in arg_types if isinstance(arg_type, ast.MapType)]
        return least_common_supertype(map_types, dialect=dialect) if map_types else ast.UnknownType()

    if normalized_name == "mapextractkeylike" and arg_types:
        return _infer_map_filter_type(arg_types[0])

    if normalized_name == "mappopulateseries" and arg_types:
        return _infer_map_filter_type(arg_types[0])

    if normalized_name == "mapfilter" and len(arg_types) >= 2:
        return _infer_map_filter_type(arg_types[1])

    if normalized_name == "mapapply" and len(arg_types) >= 2:
        return _infer_map_apply_type(arg_types=arg_types, args=args)

    if normalized_name == "arrayconcat":
        return _infer_array_concat_type(arg_types, dialect=dialect)

    if normalized_name == "arrayzip":
        return _infer_array_zip_type(arg_types)

    if normalized_name == "arrayflatten" and arg_types:
        return _infer_array_flatten_type(arg_types[0])

    if (
        normalized_name
        in {
            "arrayslice",
            "arrayreverse",
            "arraydistinct",
            "arraypopback",
            "arraypopfront",
            "arraycompact",
        }
        and arg_types
    ):
        return infer_array_slice_constant_type(arg_types[0])

    if normalized_name in {"arraysort", "arrayreversesort", "arrayfill", "arrayreversefill"} and arg_types:
        array_arg_types = _higher_order_array_arg_types(arg_types, args=args)
        return infer_array_slice_constant_type(array_arg_types[0]) if array_arg_types else ast.UnknownType()

    if normalized_name in {"arraysplit", "arrayreversesplit"} and arg_types:
        array_arg_types = _higher_order_array_arg_types(arg_types, args=args)
        if not array_arg_types:
            return ast.UnknownType()
        split_array_type = infer_array_slice_constant_type(array_arg_types[0])
        if isinstance(split_array_type, ast.UnknownType):
            return split_array_type
        return ast.ArrayType(nullable=split_array_type.nullable, item_type=split_array_type)

    if normalized_name == "arrayfold":
        return _infer_array_fold_type(arg_types=arg_types, args=args)

    if normalized_name in {"arrayelement", "arrayjoin"} and arg_types:
        return infer_array_access_constant_type(arg_types[0])

    if normalized_name in {"arrayfirst", "arraylast"} and arg_types:
        return infer_array_access_constant_type(arg_types[-1])

    if normalized_name in {"arrayfirstindex", "arraylastindex", "arraycount"}:
        return ast.IntegerType(nullable=False)

    if normalized_name in {"arrayenumerate", "arrayenumerateuniq", "arrayenumeratedense", "range"}:
        return ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False))

    if normalized_name == "arraymap":
        return _infer_higher_order_array_type(arg_types, args=args, dialect=dialect, use_lambda_return=True)

    if normalized_name == "arrayfilter":
        return _infer_higher_order_array_type(arg_types, args=args, dialect=dialect, use_lambda_return=False)

    if normalized_name in {"arrayexists", "arrayall"}:
        return ast.BooleanType(nullable=False)

    if normalized_name in {"arraysum", "arrayavg", "arraymin", "arraymax"} and arg_types:
        item_type = infer_array_access_constant_type(arg_types[-1])
        if normalized_name == "arrayavg":
            return ast.FloatType(nullable=item_type.nullable)
        return item_type

    if normalized_name == "arrayreduce":
        return _infer_array_reduce_type(arg_types=arg_types, args=args)

    if (
        normalized_name
        in {
            "arrayresize",
            "arrayrotateleft",
            "arrayrotateright",
            "arraycumsum",
            "arraycumsumnonnegative",
            "arraydifference",
        }
        and arg_types
    ):
        # Return an array whose element type matches the input. Width/sign details (e.g. a cumulative
        # sum widening, or a difference turning unsigned into signed) aren't tracked by the
        # compatibility layer, so the family-preserving input type is the precise-enough answer.
        return infer_array_slice_constant_type(arg_types[0])

    # Array-returning helpers: array-level nullability propagates from the arguments (a nullable input
    # can make the whole result NULL), while the element type comes from _array_element_type so array
    # nullability isn't folded into the element. Matches _infer_array_concat_type.
    if normalized_name in {"arraypushback", "arraypushfront"} and len(arg_types) >= 2:
        item_type = least_common_supertype([_array_element_type(arg_types[0]), arg_types[1]], dialect=dialect)
        return ast.ArrayType(nullable=any(arg_type.nullable for arg_type in arg_types), item_type=item_type)

    if normalized_name == "arraywithconstant" and len(arg_types) >= 2:
        return ast.ArrayType(
            nullable=any(arg_type.nullable for arg_type in arg_types), item_type=dataclasses.replace(arg_types[1])
        )

    if normalized_name == "arrayintersect" and arg_types:
        return ast.ArrayType(
            nullable=any(arg_type.nullable for arg_type in arg_types),
            item_type=least_common_supertype(
                [_array_element_type(arg_type) for arg_type in arg_types], dialect=dialect
            ),
        )

    # Fixed result families. Propagate input nullability (matching arraySum/arrayAvg) rather than
    # asserting non-null: over a nullable array these can be NULL, and claiming non-null would let the
    # printer drop a load-bearing null wrapper. Keeping the wrapper when unsure is the safe direction.
    if normalized_name == "arrayuniq":
        return ast.IntegerType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name == "arraystringconcat":
        return ast.StringType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in {"arrayproduct", "arrayauc"}:
        return ast.FloatType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name == "reverse" and arg_types:
        # reverse is polymorphic identity: String -> String, Array[T] -> Array[T].
        return dataclasses.replace(arg_types[0])

    if normalized_name == "tuple":
        return ast.TupleType(nullable=False, item_types=[dataclasses.replace(arg_type) for arg_type in arg_types])

    if normalized_name == "tupleelement" and len(arg_types) >= 2:
        index = _constant_int(args[1]) if args and len(args) > 1 else None
        if index is not None:
            return infer_tuple_access_constant_type(arg_types[0], index)
        field_name = _constant_string(args[1]) if args and len(args) > 1 else None
        if field_name is not None:
            return infer_tuple_name_access_constant_type(arg_types[0], field_name)
        return ast.UnknownType()

    aggregate_type = _infer_aggregate_function_type(normalized_name, arg_types)
    if aggregate_type is not None:
        return aggregate_type

    if normalized_name.endswith("state"):
        return ast.UnknownType(nullable=False)

    if normalized_name.endswith("merge") or normalized_name.endswith("mergeif"):
        return ast.UnknownType(nullable=False)

    return None


def _conversion_nullable(normalized_name: str, arg_types: list[ast.ConstantType]) -> bool:
    if normalized_name.endswith("orzero") or normalized_name.endswith("ordefault"):
        return False
    return any(arg_type.nullable for arg_type in arg_types) or normalized_name in {
        "toint",
        "tofloat",
        "tobool",
        "touuid",
        "todecimal",
        "parsedatetime",
        "parsedatetimebesteffort",
    }


def _infer_cast_function_type(
    arg_types: list[ast.ConstantType],
    args: Optional[list[ast.Expr]],
    dialect: HogQLDialect,
    nullable_on_failure: bool,
) -> ast.ConstantType:
    if not args or len(args) < 2:
        return ast.UnknownType()

    target_type_name = _constant_string(args[1])
    if target_type_name is None:
        return ast.UnknownType()

    target_type = parse_sql_runtime_type(target_type_name, dialect=dialect)
    if target_type.family == "unknown":
        return ast.UnknownType(nullable=True)

    input_nullable = any(arg_type.nullable for arg_type in arg_types[:1])
    result_type = constant_type_from_runtime_type(target_type.with_nullable(target_type.nullable or input_nullable))
    result_type.nullable = result_type.nullable or nullable_on_failure
    return result_type


def _infer_reinterpret_type(normalized_name: str, arg_types: list[ast.ConstantType]) -> ast.ConstantType | None:
    nullable = any(arg_type.nullable for arg_type in arg_types)
    if normalized_name.startswith("reinterpretasuint") or normalized_name.startswith("reinterpretasint"):
        return ast.IntegerType(nullable=nullable)
    if normalized_name.startswith("reinterpretasfloat"):
        return ast.FloatType(nullable=nullable)
    if normalized_name == "reinterpretasuuid":
        return ast.UUIDType(nullable=nullable)
    return None


def _infer_array_concat_type(arg_types: list[ast.ConstantType], dialect: HogQLDialect) -> ast.ArrayType:
    item_types: list[ast.ConstantType] = []
    nullable = False
    for arg_type in arg_types:
        nullable = nullable or arg_type.nullable
        item_types.append(_array_element_type(arg_type))
    return ast.ArrayType(nullable=nullable, item_type=least_common_supertype(item_types, dialect=dialect))


def _infer_array_zip_type(arg_types: list[ast.ConstantType]) -> ast.ArrayType:
    return ast.ArrayType(
        nullable=any(arg_type.nullable for arg_type in arg_types),
        item_type=ast.TupleType(nullable=False, item_types=[_array_element_type(arg_type) for arg_type in arg_types]),
    )


def _infer_array_flatten_type(array_type: ast.ConstantType) -> ast.ConstantType:
    if isinstance(array_type, ast.StringArrayType):
        return ast.ArrayType(nullable=array_type.nullable, item_type=ast.StringType(nullable=False))
    if not isinstance(array_type, ast.ArrayType):
        return ast.UnknownType()

    nullable = array_type.nullable
    item_type = array_type.item_type
    while isinstance(item_type, ast.ArrayType):
        nullable = nullable or item_type.nullable
        item_type = item_type.item_type

    if isinstance(item_type, ast.StringArrayType):
        return ast.ArrayType(
            nullable=nullable or item_type.nullable,
            item_type=ast.StringType(nullable=False),
        )

    return ast.ArrayType(nullable=nullable, item_type=dataclasses.replace(item_type))


def _higher_order_array_arg_types(
    arg_types: list[ast.ConstantType], args: Optional[list[ast.Expr]]
) -> list[ast.ConstantType]:
    if args and isinstance(args[0], ast.Lambda):
        return arg_types[1:]
    return arg_types


def _lambda_return_constant_type(lambda_node: ast.Lambda) -> ast.ConstantType | None:
    if not isinstance(lambda_node.expr, ast.Expr) or lambda_node.expr.type is None:
        return None
    return _context_free_constant_type(lambda_node.expr.type)


def _infer_array_fold_type(arg_types: list[ast.ConstantType], args: Optional[list[ast.Expr]]) -> ast.ConstantType:
    if len(arg_types) < 3:
        return ast.UnknownType()
    if args and isinstance(args[0], ast.Lambda):
        lambda_expr_type = _lambda_return_constant_type(args[0])
        if lambda_expr_type is not None and not isinstance(lambda_expr_type, ast.UnknownType):
            return lambda_expr_type
    return dataclasses.replace(arg_types[-1])


def _array_element_type(array_type: ast.ConstantType) -> ast.ConstantType:
    if isinstance(array_type, ast.ArrayType):
        return dataclasses.replace(array_type.item_type)
    if isinstance(array_type, ast.StringArrayType):
        return ast.StringType(nullable=False)
    return ast.UnknownType()


def _infer_array_reduce_type(arg_types: list[ast.ConstantType], args: Optional[list[ast.Expr]]) -> ast.ConstantType:
    if not args or len(args) < 2:
        return ast.UnknownType()

    aggregate_name = _constant_string(args[0])
    if aggregate_name is None:
        return ast.UnknownType()

    array_item_types = [_array_element_type(arg_type) for arg_type in arg_types[1:]]
    if not array_item_types:
        return ast.UnknownType()

    normalized_aggregate = _normalize_array_reduce_aggregate_name(aggregate_name)
    return _infer_aggregate_function_type(normalized_aggregate, array_item_types) or ast.UnknownType()


def _normalize_array_reduce_aggregate_name(aggregate_name: str) -> str:
    return aggregate_name.split("(", 1)[0].strip().lower()


def _infer_aggregate_function_type(normalized_name: str, arg_types: list[ast.ConstantType]) -> ast.ConstantType | None:
    # A ClickHouse aggregate is a base aggregate plus zero or more stackable combinator suffixes
    # (-If, -Array, -ForEach, -OrNull, -OrDefault, -Distinct, -State, -Merge). Peel known combinators
    # first so the base return type is computed once and each suffix transforms it, instead of
    # enumerating every base×combinator permutation. This must run before the base checks below so a
    # greedy `startswith` match (e.g. "quantiles") can't swallow a combinator such as -ForEach.
    combinator_type = _infer_aggregate_combinator_type(normalized_name, arg_types)
    if combinator_type is not None:
        return combinator_type

    state_or_merge_type = _infer_aggregate_state_or_merge_type(normalized_name, arg_types)
    if state_or_merge_type is not None:
        return state_or_merge_type

    if normalized_name in {"count", "uniq", "uniqexact", "uniqhll12", "uniqtheta"}:
        return ast.IntegerType(nullable=False)

    if normalized_name == "sum" and arg_types:
        input_type = arg_types[0]
        if isinstance(input_type, ast.FloatType):
            return ast.FloatType(nullable=input_type.nullable)
        if isinstance(input_type, ast.DecimalType):
            return ast.DecimalType(nullable=input_type.nullable)
        return ast.IntegerType(nullable=input_type.nullable)

    if normalized_name.startswith("quantiles") and not _is_aggregate_state_or_merge(normalized_name):
        return ast.ArrayType(
            nullable=False,
            item_type=ast.FloatType(nullable=any(arg_type.nullable for arg_type in arg_types)),
        )

    if (
        normalized_name in {"avg", "stddevpop", "stddevsamp", "varpop", "varsamp"}
        or normalized_name.startswith("median")
        or normalized_name.startswith("quantile")
    ) and not _is_aggregate_state_or_merge(normalized_name):
        return ast.FloatType(nullable=any(arg_type.nullable for arg_type in arg_types))

    if normalized_name in {"min", "max", "any", "anylast", "argmin", "argmax"} and arg_types:
        return dataclasses.replace(arg_types[0])

    if normalized_name in {"grouparray", "array_agg", "groupuniqarray"} and arg_types:
        return ast.ArrayType(nullable=False, item_type=dataclasses.replace(arg_types[0]))

    return None


# ClickHouse aggregate combinator suffixes this rule understands. Each one transforms the base
# aggregate's return type. Combinators not listed here (-Map, -Resample, -SimpleState, -MergeState,
# argument-shape variants, …) are deliberately left to fall through to UnknownType rather than risk a
# confidently-wrong type. -State/-Merge keep their dedicated handling in
# _infer_aggregate_state_or_merge_type because they carry/consume AggregateState payloads.
_AGGREGATE_COMBINATOR_SUFFIXES: tuple[str, ...] = ("ordefault", "ornull", "distinct", "foreach", "array", "if")


def _infer_aggregate_combinator_type(
    normalized_name: str, arg_types: list[ast.ConstantType]
) -> ast.ConstantType | None:
    for suffix in _AGGREGATE_COMBINATOR_SUFFIXES:
        if not normalized_name.endswith(suffix) or len(normalized_name) <= len(suffix):
            continue
        base_name = normalized_name[: -len(suffix)]
        base_arg_types = _aggregate_combinator_base_arg_types(suffix, arg_types)
        # Only accept the peel if what remains is itself a known aggregate (possibly with further
        # combinators). Otherwise the suffix was a coincidence — try the next, then fall through to
        # Unknown. This keeps the rule conservative: a wrong type is worse than no type.
        base_type = _infer_aggregate_function_type(base_name, base_arg_types)
        if base_type is None:
            continue
        return _apply_aggregate_combinator(suffix, base_type)
    return None


def _aggregate_combinator_base_arg_types(suffix: str, arg_types: list[ast.ConstantType]) -> list[ast.ConstantType]:
    if suffix == "if":
        # -If appends a UInt8 condition the base aggregate never sees.
        return arg_types[:-1]
    if suffix in {"array", "foreach"}:
        # -Array/-ForEach aggregate over array arguments, so the base sees each element type.
        return [infer_array_access_constant_type(arg_type) for arg_type in arg_types]
    return arg_types


def _apply_aggregate_combinator(suffix: str, base_type: ast.ConstantType) -> ast.ConstantType:
    if suffix == "ornull":
        return dataclasses.replace(base_type, nullable=True)
    if suffix == "ordefault":
        return dataclasses.replace(base_type, nullable=False)
    if suffix == "foreach":
        return ast.ArrayType(nullable=False, item_type=base_type)
    # -If, -Array and -Distinct change which rows/values are aggregated, not the result type.
    return base_type


def _is_aggregate_state_or_merge(normalized_name: str) -> bool:
    return normalized_name.endswith("state") or normalized_name.endswith("merge") or normalized_name.endswith("mergeif")


def _infer_aggregate_state_or_merge_type(
    normalized_name: str, arg_types: list[ast.ConstantType]
) -> ast.ConstantType | None:
    state_base_name = _strip_aggregate_suffix(normalized_name, ("stateif", "state"))
    if state_base_name is not None:
        state_arg_types = arg_types[:-1] if normalized_name.endswith("stateif") else arg_types
        wrapped_type = _infer_aggregate_function_type(state_base_name, state_arg_types)
        if wrapped_type is None:
            return None
        return ast.AggregateStateType(nullable=False, wrapped_type=wrapped_type)

    merge_base_name = _strip_aggregate_suffix(normalized_name, ("mergeif", "merge"))
    if merge_base_name is not None:
        if arg_types and isinstance(arg_types[0], ast.AggregateStateType):
            return dataclasses.replace(arg_types[0].wrapped_type)
        return _infer_known_merge_result_type(merge_base_name, arg_types)

    return None


def _infer_known_merge_result_type(base_name: str, arg_types: list[ast.ConstantType]) -> ast.ConstantType | None:
    if base_name in {"count", "countdistinct"} or base_name.startswith("uniq"):
        return ast.IntegerType(nullable=False)
    if base_name.startswith("quantiles"):
        return ast.ArrayType(
            nullable=False,
            item_type=ast.FloatType(nullable=any(arg_type.nullable for arg_type in arg_types)),
        )
    if base_name.startswith("quantile") or base_name.startswith("median") or base_name in {"avg"}:
        return ast.FloatType(nullable=any(arg_type.nullable for arg_type in arg_types))
    return None


def _strip_aggregate_suffix(normalized_name: str, suffixes: tuple[str, ...]) -> str | None:
    for suffix in suffixes:
        if normalized_name.endswith(suffix):
            return normalized_name[: -len(suffix)]
    return None


def _infer_map_type(arg_types: list[ast.ConstantType], dialect: HogQLDialect) -> ast.ConstantType:
    if not arg_types:
        return ast.MapType(nullable=False)
    if len(arg_types) % 2 != 0:
        return ast.UnknownType()
    return ast.MapType(
        nullable=False,
        key_type=least_common_supertype(arg_types[::2], dialect=dialect),
        value_type=least_common_supertype(arg_types[1::2], dialect=dialect),
    )


def _infer_map_from_arrays_type(arg_types: list[ast.ConstantType], dialect: HogQLDialect) -> ast.MapType:
    key_type = infer_array_access_constant_type(arg_types[0])
    value_type = infer_array_access_constant_type(arg_types[1])
    return ast.MapType(
        nullable=arg_types[0].nullable or arg_types[1].nullable,
        key_type=least_common_supertype([key_type], dialect=dialect),
        value_type=least_common_supertype([value_type], dialect=dialect),
    )


def _infer_map_items_type(map_type: ast.ConstantType, keys: bool) -> ast.ArrayType:
    if not isinstance(map_type, ast.MapType):
        return ast.ArrayType(nullable=True, item_type=ast.UnknownType())
    item_type = map_type.key_type if keys else map_type.value_type
    return ast.ArrayType(nullable=map_type.nullable, item_type=dataclasses.replace(item_type))


def _infer_map_filter_type(map_type: ast.ConstantType) -> ast.ConstantType:
    if not isinstance(map_type, ast.MapType):
        return ast.UnknownType()
    return dataclasses.replace(
        map_type,
        key_type=dataclasses.replace(map_type.key_type),
        value_type=dataclasses.replace(map_type.value_type),
    )


def _infer_map_apply_type(arg_types: list[ast.ConstantType], args: Optional[list[ast.Expr]]) -> ast.ConstantType:
    map_type = arg_types[1]
    if not isinstance(map_type, ast.MapType):
        return ast.UnknownType()

    if args and isinstance(args[0], ast.Lambda):
        lambda_return_type = _lambda_return_constant_type(args[0])
        if isinstance(lambda_return_type, ast.TupleType) and len(lambda_return_type.item_types) >= 2:
            return ast.MapType(
                nullable=map_type.nullable,
                key_type=dataclasses.replace(lambda_return_type.item_types[0]),
                value_type=dataclasses.replace(lambda_return_type.item_types[1]),
            )

    return _infer_map_filter_type(map_type)


def _infer_higher_order_array_type(
    arg_types: list[ast.ConstantType], args: Optional[list[ast.Expr]], dialect: HogQLDialect, use_lambda_return: bool
) -> ast.ConstantType:
    array_arg_types = _higher_order_array_arg_types(arg_types, args)
    if not array_arg_types:
        return ast.UnknownType()
    first_array_type = array_arg_types[0]
    if use_lambda_return and args and isinstance(args[0], ast.Lambda):
        lambda_expr_type = _lambda_return_constant_type(args[0])
        if lambda_expr_type is not None and not isinstance(lambda_expr_type, ast.UnknownType):
            if isinstance(first_array_type, ast.ArrayType):
                return ast.ArrayType(nullable=first_array_type.nullable, item_type=lambda_expr_type)
            if isinstance(first_array_type, ast.StringArrayType):
                return ast.ArrayType(nullable=first_array_type.nullable, item_type=lambda_expr_type)
            return ast.ArrayType(nullable=True, item_type=lambda_expr_type)
    if isinstance(first_array_type, ast.ArrayType):
        return ast.ArrayType(
            nullable=first_array_type.nullable, item_type=dataclasses.replace(first_array_type.item_type)
        )
    if isinstance(first_array_type, ast.StringArrayType):
        return ast.ArrayType(nullable=first_array_type.nullable, item_type=ast.StringType(nullable=False))
    return ast.ArrayType(nullable=True, item_type=least_common_supertype(array_arg_types, dialect=dialect))


def _context_free_constant_type(type_: ast.Type) -> ast.ConstantType | None:
    if isinstance(type_, ast.ConstantType):
        return dataclasses.replace(type_)
    if isinstance(type_, ast.CallType):
        return dataclasses.replace(type_.return_type)
    if isinstance(type_, ast.FieldAliasType):
        return _context_free_constant_type(type_.type)
    if isinstance(type_, ast.LambdaArgumentType):
        return dataclasses.replace(type_.constant_type) if type_.constant_type is not None else ast.UnknownType()
    return None


def _infer_json_extract_type(
    arg_types: list[ast.ConstantType], args: Optional[list[ast.Expr]], dialect: HogQLDialect
) -> ast.ConstantType | None:
    if not args:
        return None

    type_arg = args[-1]
    if not isinstance(type_arg, ast.Constant) or not isinstance(type_arg.value, str):
        return None

    runtime_type = parse_sql_runtime_type(type_arg.value, dialect=dialect)
    if runtime_type.family == "unknown":
        return None
    result_type = constant_type_from_runtime_type(runtime_type)
    result_type.nullable = result_type.nullable or any(arg_type.nullable for arg_type in arg_types)
    return result_type


def _infer_json_extract_keys_and_values_type(
    arg_types: list[ast.ConstantType], args: Optional[list[ast.Expr]], dialect: HogQLDialect
) -> ast.ConstantType | None:
    if not args:
        return None

    type_arg = args[-1]
    if not isinstance(type_arg, ast.Constant) or not isinstance(type_arg.value, str):
        return None

    runtime_type = parse_sql_runtime_type(type_arg.value, dialect=dialect)
    if runtime_type.family == "unknown":
        return None

    value_type = constant_type_from_runtime_type(runtime_type)
    value_type.nullable = value_type.nullable or any(arg_type.nullable for arg_type in arg_types)
    return ast.ArrayType(
        nullable=any(arg_type.nullable for arg_type in arg_types),
        item_type=ast.TupleType(
            nullable=False,
            item_types=[ast.StringType(nullable=False), value_type],
        ),
    )


def _constant_int(expr: ast.Expr) -> Optional[int]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
        return expr.value
    return None


def _constant_string(expr: ast.Expr) -> Optional[str]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    return None


def _same_tuple_width(runtime_types: list[RuntimeType]) -> bool:
    if not runtime_types:
        return False
    width = len(runtime_types[0].item_types)
    return all(len(type_.item_types) == width for type_ in runtime_types)


def _common_tuple_field_names(runtime_types: list[RuntimeType]) -> tuple[Optional[str], ...]:
    if not runtime_types:
        return ()
    field_names = runtime_types[0].field_names
    if not field_names:
        return ()
    if all(type_.field_names == field_names for type_ in runtime_types):
        return field_names
    return ()


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
