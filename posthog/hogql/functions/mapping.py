from itertools import chain
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.ast import IntegerType, StringType
from posthog.hogql.base import UnknownType
from posthog.hogql.language_mappings import LANGUAGE_CODES, LANGUAGE_NAMES

from .aggregations import HOGQL_AGGREGATIONS
from .clickhouse.arithmetic import ARITHMETIC_FUNCTIONS
from .clickhouse.arrays import ARRAYS_FUNCTIONS
from .clickhouse.conversions import CONVERSION_FUNCTIONS
from .clickhouse.datetime import DATETIME_AND_INTERVAL_FUNCTIONS
from .clickhouse.geo import GEO_FUNCTIONS
from .clickhouse.json import JSON_FUNCTIONS
from .clickhouse.mathematical import MATH_FUNCTIONS
from .clickhouse.strings import STRINGS_FUNCTIONS
from .config import HOGQL_PERMITTED_PARAMETRIC_FUNCTIONS
from .core import HogQLFunctionMeta
from .posthog import HOGQL_POSTHOG_FUNCTIONS
from .udfs import UDFS

HOGQL_COMPARISON_MAPPING: dict[str, ast.CompareOperationOp] = {
    "equals": ast.CompareOperationOp.Eq,
    "notEquals": ast.CompareOperationOp.NotEq,
    "less": ast.CompareOperationOp.Lt,
    "greater": ast.CompareOperationOp.Gt,
    "lessOrEquals": ast.CompareOperationOp.LtEq,
    "greaterOrEquals": ast.CompareOperationOp.GtEq,
    "like": ast.CompareOperationOp.Like,
    "ilike": ast.CompareOperationOp.ILike,
    "notLike": ast.CompareOperationOp.NotLike,
    "notILike": ast.CompareOperationOp.NotILike,
    "in": ast.CompareOperationOp.In,
    "notIn": ast.CompareOperationOp.NotIn,
}

HOGQL_CLICKHOUSE_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    **ARITHMETIC_FUNCTIONS,
    **ARRAYS_FUNCTIONS,
    **CONVERSION_FUNCTIONS,
    **DATETIME_AND_INTERVAL_FUNCTIONS,
    **GEO_FUNCTIONS,
    **JSON_FUNCTIONS,
    **MATH_FUNCTIONS,
    **STRINGS_FUNCTIONS,
    # comparison
    "equals": HogQLFunctionMeta("equals", 2, 2),
    "notEquals": HogQLFunctionMeta("notEquals", 2, 2),
    "less": HogQLFunctionMeta("less", 2, 2),
    "greater": HogQLFunctionMeta("greater", 2, 2),
    "lessOrEquals": HogQLFunctionMeta("lessOrEquals", 2, 2),
    "greaterOrEquals": HogQLFunctionMeta("greaterOrEquals", 2, 2),
    # in
    "in": HogQLFunctionMeta("in", 2, 2),
    "notIn": HogQLFunctionMeta("notIn", 2, 2),
    # logical
    "and": HogQLFunctionMeta("and", 2, None),
    "or": HogQLFunctionMeta("or", 2, None),
    "xor": HogQLFunctionMeta("xor", 2, None),
    "not": HogQLFunctionMeta("not", 1, 1, case_sensitive=False),
    # conditional
    "if": HogQLFunctionMeta("if", 3, 3, case_sensitive=False),
    "multiIf": HogQLFunctionMeta("multiIf", 3, None),
    # maps
    "map": HogQLFunctionMeta("map", 0, None),
    "mapFromArrays": HogQLFunctionMeta("mapFromArrays", 2, 2),
    "mapAdd": HogQLFunctionMeta("mapAdd", 2, None),
    "mapSubtract": HogQLFunctionMeta("mapSubtract", 2, None),
    "mapPopulateSeries": HogQLFunctionMeta("mapPopulateSeries", 1, 3),
    "mapContains": HogQLFunctionMeta("mapContains", 2, 2),
    "mapKeys": HogQLFunctionMeta("mapKeys", 1, 1),
    "mapValues": HogQLFunctionMeta("mapValues", 1, 1),
    "mapContainsKeyLike": HogQLFunctionMeta("mapContainsKeyLike", 2, 2),
    "mapExtractKeyLike": HogQLFunctionMeta("mapExtractKeyLike", 2, 2),
    "mapApply": HogQLFunctionMeta("mapApply", 2, 2),
    "mapFilter": HogQLFunctionMeta("mapFilter", 2, 2),
    "mapUpdate": HogQLFunctionMeta("mapUpdate", 2, 2),
    # bit
    "bitAnd": HogQLFunctionMeta("bitAnd", 2, 2),
    "bitOr": HogQLFunctionMeta("bitOr", 2, 2),
    "bitXor": HogQLFunctionMeta("bitXor", 2, 2),
    "bitNot": HogQLFunctionMeta("bitNot", 1, 1),
    "bitShiftLeft": HogQLFunctionMeta("bitShiftLeft", 2, 2),
    "bitShiftRight": HogQLFunctionMeta("bitShiftRight", 2, 2),
    "bitRotateLeft": HogQLFunctionMeta("bitRotateLeft", 2, 2),
    "bitRotateRight": HogQLFunctionMeta("bitRotateRight", 2, 2),
    "bitSlice": HogQLFunctionMeta("bitSlice", 3, 3),
    "bitTest": HogQLFunctionMeta("bitTest", 2, 2),
    "bitTestAll": HogQLFunctionMeta("bitTestAll", 3, None),
    "bitTestAny": HogQLFunctionMeta("bitTestAny", 3, None),
    "bitCount": HogQLFunctionMeta("bitCount", 1, 1),
    "bitHammingDistance": HogQLFunctionMeta("bitHammingDistance", 2, 2),
    # bitmap
    "bitmapBuild": HogQLFunctionMeta("bitmapBuild", 1, 1),
    "bitmapToArray": HogQLFunctionMeta("bitmapToArray", 1, 1),
    "bitmapSubsetInRange": HogQLFunctionMeta("bitmapSubsetInRange", 3, 3),
    "bitmapSubsetLimit": HogQLFunctionMeta("bitmapSubsetLimit", 3, 3),
    "subBitmap": HogQLFunctionMeta("subBitmap", 3, 3),
    "bitmapContains": HogQLFunctionMeta("bitmapContains", 2, 2),
    "bitmapHasAny": HogQLFunctionMeta("bitmapHasAny", 2, 2),
    "bitmapHasAll": HogQLFunctionMeta("bitmapHasAll", 2, 2),
    "bitmapCardinality": HogQLFunctionMeta("bitmapCardinality", 1, 1),
    "bitmapMin": HogQLFunctionMeta("bitmapMin", 1, 1),
    "bitmapMax": HogQLFunctionMeta("bitmapMax", 1, 1),
    "bitmapTransform": HogQLFunctionMeta("bitmapTransform", 3, 3),
    "bitmapAnd": HogQLFunctionMeta("bitmapAnd", 2, 2),
    "bitmapOr": HogQLFunctionMeta("bitmapOr", 2, 2),
    "bitmapXor": HogQLFunctionMeta("bitmapXor", 2, 2),
    "bitmapAndnot": HogQLFunctionMeta("bitmapAndnot", 2, 2),
    "bitmapAndCardinality": HogQLFunctionMeta("bitmapAndCardinality", 2, 2),
    "bitmapOrCardinality": HogQLFunctionMeta("bitmapOrCardinality", 2, 2),
    "bitmapXorCardinality": HogQLFunctionMeta("bitmapXorCardinality", 2, 2),
    "bitmapAndnotCardinality": HogQLFunctionMeta("bitmapAndnotCardinality", 2, 2),
    # urls TODO
    "protocol": HogQLFunctionMeta("protocol", 1, 1),
    "domain": HogQLFunctionMeta("domain", 1, 1),
    "domainWithoutWWW": HogQLFunctionMeta("domainWithoutWWW", 1, 1),
    "topLevelDomain": HogQLFunctionMeta("topLevelDomain", 1, 1),
    "firstSignificantSubdomain": HogQLFunctionMeta("firstSignificantSubdomain", 1, 1),
    "cutToFirstSignificantSubdomain": HogQLFunctionMeta("cutToFirstSignificantSubdomain", 1, 1),
    "cutToFirstSignificantSubdomainWithWWW": HogQLFunctionMeta("cutToFirstSignificantSubdomainWithWWW", 1, 1),
    "port": HogQLFunctionMeta("port", 1, 2),
    "path": HogQLFunctionMeta("path", 1, 1),
    "pathFull": HogQLFunctionMeta("pathFull", 1, 1),
    "queryString": HogQLFunctionMeta("queryString", 1, 1),
    "fragment": HogQLFunctionMeta("fragment", 1, 1),
    "queryStringAndFragment": HogQLFunctionMeta("queryStringAndFragment", 1, 1),
    "extractURLParameter": HogQLFunctionMeta("extractURLParameter", 2, 2),
    "extractURLParameters": HogQLFunctionMeta("extractURLParameters", 1, 1),
    "extractURLParameterNames": HogQLFunctionMeta("extractURLParameterNames", 1, 1),
    "URLHierarchy": HogQLFunctionMeta("URLHierarchy", 1, 1),
    "URLPathHierarchy": HogQLFunctionMeta("URLPathHierarchy", 1, 1),
    "encodeURLComponent": HogQLFunctionMeta("encodeURLComponent", 1, 1),
    "decodeURLComponent": HogQLFunctionMeta("decodeURLComponent", 1, 1),
    "encodeURLFormComponent": HogQLFunctionMeta("encodeURLFormComponent", 1, 1),
    "decodeURLFormComponent": HogQLFunctionMeta("decodeURLFormComponent", 1, 1),
    "netloc": HogQLFunctionMeta("netloc", 1, 1),
    "cutWWW": HogQLFunctionMeta("cutWWW", 1, 1),
    "cutQueryString": HogQLFunctionMeta("cutQueryString", 1, 1),
    "cutFragment": HogQLFunctionMeta("cutFragment", 1, 1),
    "cutQueryStringAndFragment": HogQLFunctionMeta("cutQueryStringAndFragment", 1, 1),
    "cutURLParameter": HogQLFunctionMeta("cutURLParameter", 2, 2),
    # tuples
    "tuple": HogQLFunctionMeta("tuple", 0, None),
    "tupleElement": HogQLFunctionMeta("tupleElement", 2, 3),
    "untuple": HogQLFunctionMeta("untuple", 1, 1),
    "tupleHammingDistance": HogQLFunctionMeta("tupleHammingDistance", 2, 2),
    "tupleToNameValuePairs": HogQLFunctionMeta("tupleToNameValuePairs", 1, 1),
    "tuplePlus": HogQLFunctionMeta("tuplePlus", 2, 2),
    "tupleMinus": HogQLFunctionMeta("tupleMinus", 2, 2),
    "tupleMultiply": HogQLFunctionMeta("tupleMultiply", 2, 2),
    "tupleDivide": HogQLFunctionMeta("tupleDivide", 2, 2),
    "tupleNegate": HogQLFunctionMeta("tupleNegate", 1, 1),
    "tupleMultiplyByNumber": HogQLFunctionMeta("tupleMultiplyByNumber", 2, 2),
    "tupleDivideByNumber": HogQLFunctionMeta("tupleDivideByNumber", 2, 2),
    "dotProduct": HogQLFunctionMeta("dotProduct", 2, 2),
    # other
    "isFinite": HogQLFunctionMeta("isFinite", 1, 1),
    "isInfinite": HogQLFunctionMeta("isInfinite", 1, 1),
    "ifNotFinite": HogQLFunctionMeta("ifNotFinite", 1, 1),
    "isNaN": HogQLFunctionMeta("isNaN", 1, 1),
    "bar": HogQLFunctionMeta("bar", 4, 4),
    "transform": HogQLFunctionMeta("transform", 3, 4),
    "formatReadableDecimalSize": HogQLFunctionMeta("formatReadableDecimalSize", 1, 1),
    "formatReadableSize": HogQLFunctionMeta("formatReadableSize", 1, 1),
    "formatReadableQuantity": HogQLFunctionMeta("formatReadableQuantity", 1, 1),
    "formatReadableTimeDelta": HogQLFunctionMeta("formatReadableTimeDelta", 1, 2),
    "least": HogQLFunctionMeta("least", 2, 2, case_sensitive=False),
    "greatest": HogQLFunctionMeta("greatest", 2, 2, case_sensitive=False),
    "indexHint": HogQLFunctionMeta("indexHint", 1, 1),
    "extractIPv4Substrings": HogQLFunctionMeta("extractIPv4Substrings", 1, 1),
    # time window
    "tumble": HogQLFunctionMeta("tumble", 2, 2),
    "hop": HogQLFunctionMeta("hop", 3, 3),
    "tumbleStart": HogQLFunctionMeta("tumbleStart", 1, 3),
    "tumbleEnd": HogQLFunctionMeta("tumbleEnd", 1, 3),
    "hopStart": HogQLFunctionMeta("hopStart", 1, 3),
    "hopEnd": HogQLFunctionMeta("hopEnd", 1, 3),
    # distance window
    "L1Norm": HogQLFunctionMeta("L1Norm", 1, 1),
    "L2Norm": HogQLFunctionMeta("L2Norm", 1, 1),
    "LinfNorm": HogQLFunctionMeta("LinfNorm", 1, 1),
    "LpNorm": HogQLFunctionMeta("LpNorm", 2, 2),
    "L1Distance": HogQLFunctionMeta("L1Distance", 2, 2),
    "L2Distance": HogQLFunctionMeta("L2Distance", 2, 2),
    "LinfDistance": HogQLFunctionMeta("LinfDistance", 2, 2),
    "LpDistance": HogQLFunctionMeta("LpDistance", 3, 3),
    "L1Normalize": HogQLFunctionMeta("L1Normalize", 1, 1),
    "L2Normalize": HogQLFunctionMeta("L2Normalize", 1, 1),
    "LinfNormalize": HogQLFunctionMeta("LinfNormalize", 1, 1),
    "LpNormalize": HogQLFunctionMeta("LpNormalize", 2, 2),
    "cosineDistance": HogQLFunctionMeta("cosineDistance", 2, 2),
    # window functions
    "rank": HogQLFunctionMeta("rank"),
    "dense_rank": HogQLFunctionMeta("dense_rank"),
    "row_number": HogQLFunctionMeta("row_number"),
    "first_value": HogQLFunctionMeta("first_value", 1, 1),
    "last_value": HogQLFunctionMeta("last_value", 1, 1),
    "nth_value": HogQLFunctionMeta("nth_value", 2, 2),
    "lagInFrame": HogQLFunctionMeta("lagInFrame", 1, 3),
    "leadInFrame": HogQLFunctionMeta("leadInFrame", 1, 3),
    # Window functions in PostgreSQL style
    "lag": HogQLFunctionMeta(
        "lagInFrame",
        1,
        3,
        signatures=[
            ((UnknownType(),), UnknownType()),
            ((UnknownType(), IntegerType()), UnknownType()),
            ((UnknownType(), IntegerType(), UnknownType()), UnknownType()),
        ],
    ),
    "lead": HogQLFunctionMeta(
        "leadInFrame",
        1,
        3,
        signatures=[
            ((UnknownType(),), UnknownType()),
            ((UnknownType(), IntegerType()), UnknownType()),
            ((UnknownType(), IntegerType(), UnknownType()), UnknownType()),
        ],
    ),
    # Translates languages codes to full language name
    "languageCodeToName": HogQLFunctionMeta(
        clickhouse_name="transform",
        min_args=1,
        max_args=1,
        suffix_args=[
            ast.Constant(value=LANGUAGE_CODES),
            ast.Constant(value=LANGUAGE_NAMES),
            ast.Constant(value="Unknown"),
        ],
        signatures=[((StringType(),), StringType())],
    ),
}


HOGQL_CLICKHOUSE_FUNCTIONS.update(UDFS)

ALL_EXPOSED_FUNCTION_NAMES = [
    name for name in chain(HOGQL_CLICKHOUSE_FUNCTIONS.keys(), HOGQL_AGGREGATIONS.keys()) if not name.startswith("_")
]


def _find_function(name: str, functions: dict[str, HogQLFunctionMeta]) -> Optional[HogQLFunctionMeta]:
    func = functions.get(name)
    if func is not None:
        return func

    func = functions.get(name.lower())
    if func is None:
        return None

    # If we haven't found a function with the case preserved, but we have found it in lowercase,
    # then the function names are different case-wise only.
    if func.case_sensitive:
        return None

    return func


def find_hogql_aggregation(name: str) -> Optional[HogQLFunctionMeta]:
    return _find_function(name, HOGQL_AGGREGATIONS)


def find_hogql_function(name: str) -> Optional[HogQLFunctionMeta]:
    return _find_function(name, HOGQL_CLICKHOUSE_FUNCTIONS)


def find_hogql_posthog_function(name: str) -> Optional[HogQLFunctionMeta]:
    return _find_function(name, HOGQL_POSTHOG_FUNCTIONS)


def is_allowed_parametric_function(name: str) -> bool:
    # No case-insensitivity for parametric functions
    return name in HOGQL_PERMITTED_PARAMETRIC_FUNCTIONS
