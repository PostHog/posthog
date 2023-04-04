# HogQL -> ClickHouse allowed transformations
from typing import Optional, Dict, Tuple

from pydantic import BaseModel, Extra

CLICKHOUSE_FUNCTIONS: Dict[str, Tuple[str, int | None, int | None]] = {
    # arithmetic
    "plus": ("plus", 2, 2),
    "minus": ("minus", 2, 2),
    "multiply": ("multiply", 2, 2),
    "divide": ("divide", 2, 2),
    "intDiv": ("intDiv", 2, 2),
    "intDivOrZero": ("intDivOrZero", 2, 2),
    "modulo": ("modulo", 2, 2),
    "moduloOrZero": ("moduloOrZero", 2, 2),
    "positiveModulo": ("positiveModulo", 2, 2),
    "negate": ("negate", 1, 1),
    "abs": ("abs", 1, 1),
    "gcd": ("gcd", 2, 2),
    "lcm": ("lcm", 2, 2),
    "max2": ("max2", 2, 2),
    "min2": ("min2", 2, 2),
    "multiplyDecimal": ("multiplyDecimal", 2, 3),
    "divideDecimal": ("divideDecimal", 2, 3),
    # arrays TODO
    "array": ("array", None, None),
    # comparison
    "equals": ("equals", 2, 2),
    "notEquals": ("notEquals", 2, 2),
    "less": ("less", 2, 2),
    "greater": ("greater", 2, 2),
    "lessOrEquals": ("lessOrEquals", 2, 2),
    "greaterOrEquals": ("greaterOrEquals", 2, 2),
    # logical
    "and": ("and", 2, None),
    "or": ("or", 2, None),
    "xor": ("xor", 2, None),
    "not": ("not", 1, 1),
    # type conversions
    "toInt": ("toInt64OrNull", 1, 1),
    "toFloat": ("toFloat64OrNull", 1, 1),
    "toDecimal": ("toDecimal64OrNull", 1, 1),
    "toDate": ("toDateOrNull", 1, 1),
    "toDateTime": ("toDateTimeOrNull", 1, 1),
    "toUUID": ("toUUIDOrNull", 1, 1),
    "toString": ("toString", 1, 1),
    "toJSONString": ("toJSONString", 1, 1),
    "parseDateTime": ("parseDateTimeOrNull", 2, 2),
    "parseDateTimeBestEffort": ("parseDateTimeBestEffortOrNull", 2, 2),
    # dates and times TODO
    "now": ("now", 0, 0),
    "NOW": ("now", 0, 0),
    "toMonday": ("toMonday", 1, 1),
    "toStartOfYear": ("toStartOfYear", 1, 1),
    "toStartOfQuarter": ("toStartOfQuarter", 1, 1),
    "toStartOfMonth": ("toStartOfMonth", 1, 1),
    "toStartOfWeek": ("toStartOfWeek", 1, 1),
    "toStartOfDay": ("toStartOfDay", 1, 1),
    "toStartOfHour": ("toStartOfHour", 1, 1),
    "toStartOfMinute": ("toStartOfMinute", 1, 1),
    "toStartOfSecond": ("toStartOfSecond", 1, 1),
    "toStartOfFiveMinutes": ("toStartOfFiveMinutes", 1, 1),
    "toStartOfTenMinutes": ("toStartOfTenMinutes", 1, 1),
    "toStartOfFifteenMinutes": ("toStartOfFifteenMinutes", 1, 1),
    "toTimezone": ("toTimezone", 2, 2),
    "age": ("age", 3, 3),
    "dateDiff": ("dateDiff", 3, 3),
    "dateTrunc": ("dateTrunc", 2, 2),
    "formatDateTime": ("formatDateTime", 1, 1),
    "toIntervalSecond": ("toIntervalSecond", 1, 1),
    "toIntervalMinute": ("toIntervalMinute", 1, 1),
    "toIntervalHour": ("toIntervalHour", 1, 1),
    "toIntervalDay": ("toIntervalDay", 1, 1),
    "toIntervalWeek": ("toIntervalWeek", 1, 1),
    "toIntervalMonth": ("toIntervalMonth", 1, 1),
    "toIntervalQuarter": ("toIntervalQuarter", 1, 1),
    "toIntervalYear": ("toIntervalYear", 1, 1),
    # strings TODO
    "length": ("lengthUTF8", 1, 1),
    "empty": ("empty", 1, 1),
    "notEmpty": ("notEmpty", 1, 1),
    "leftPad": ("leftPad", 1, 1),
    "rightPad": ("rightPad", 1, 1),
    "lower": ("lower", 1, 1),
    "upper": ("upper", 1, 1),
    "repeat": ("repeat", 1, 1),
    "format": ("format", 1, 1),
    "concat": ("concat", 1, 1),
    "coalesce": ("coalesce", 1, None),
    "substring": ("substringUTF8", 1, 1),
    "appendTrailingCharIfAbsent": ("appendTrailingCharIfAbsent", 1, 1),
    "endsWith": ("endsWith", 1, 1),
    "startsWith": ("startsWith", 1, 1),
    "trim": ("trimBoth", 1, 1),
    "trimLeft": ("trimLeft", 1, 1),
    "trimRight": ("trimRight", 1, 1),
    "extractTextFromHTML": ("extractTextFromHTML", 1, 1),
    # searching in strings TODO
    "match": ("match", 1, 1),
    "like": ("like", 1, 1),
    "ilike": ("ilike", 1, 1),
    "notLike": ("notLike", 1, 1),
    # replacing in strings TODO
    "replace": ("replace", 1, 1),
    "replaceOne": ("replaceOne", 1, 1),
    # conditional TODO
    "if": ("if", 2, 3),
    "multiIf": ("multiIf", 2, None),
    # mathematical TODO
    # rounding TODO
    "round": ("round", 1, 1),
    "floor": ("floor", 1, 1),
    "ceil": ("ceil", 1, 1),
    "trunc": ("trunc", 1, 1),
    # maps TODO
    # splitting strings TODO
    # bit TODO
    # urls TODO
    # json
    "isValidJSON": ("isValidJSON", 1, 1),
    "JSONHas": ("JSONHas", 1, None),
    "JSONLength": ("JSONLength", 1, None),
    "JSONArrayLength": ("JSONArrayLength", 1, None),
    "JSONType": ("JSONType", 1, None),
    "JSONExtractUInt": ("JSONExtractUInt", 1, None),
    "JSONExtractInt": ("JSONExtractInt", 1, None),
    "JSONExtractFloat": ("JSONExtractFloat", 1, None),
    "JSONExtractBool": ("JSONExtractBool", 1, None),
    "JSONExtractString": ("JSONExtractString", 1, None),
    "JSONExtractKey": ("JSONExtractKey", 1, None),
    "JSONExtractKeys": ("JSONExtractKeys", 1, None),
    "JSONExtractRaw": ("JSONExtractRaw", 1, None),
    "JSONExtractArrayRaw": ("JSONExtractArrayRaw", 1, None),
    "JSONExtractKeysAndValuesRaw": ("JSONExtractKeysAndValuesRaw", 1, None),
    # in
    # arrayjoin
    # geo
    # nullable
    # tuples
    "tuple": ("tuple", None, None),
    # time window
    # distance window
}
# Permitted HogQL aggregations
HOGQL_AGGREGATIONS = {
    "count": (0, 1),
    "countIf": (1, 2),
    "min": 1,
    "minIf": 2,
    "max": 1,
    "maxIf": 2,
    "sum": 1,
    "sumIf": 2,
    "avg": 1,
    "avgIf": 2,
    "any": 1,
    "anyIf": 2,
    "argMax": 2,
    "argMin": 2,
    # TODO: more aggregate functions?
}
# Keywords passed to ClickHouse without transformation
KEYWORDS = ["true", "false", "null"]

# Keywords you can't alias to
RESERVED_KEYWORDS = KEYWORDS + ["team_id"]

# Never return more rows than this in top level HogQL SELECT statements
DEFAULT_RETURNED_ROWS = 100
MAX_SELECT_RETURNED_ROWS = 65535

# Settings applied on top of all HogQL queries.
class HogQLSettings(BaseModel):
    class Config:
        extra = Extra.forbid

    readonly: Optional[int] = 1
    max_execution_time: Optional[int] = 60
