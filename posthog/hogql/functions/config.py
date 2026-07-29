# The list of functions allowed in parametric functions, e.g. sum in "arrayReduce('sum', [1, 2, 3])"
HOGQL_PERMITTED_PARAMETRIC_FUNCTIONS: set[str] = {
    "count",
    "countMap",
    "countMapState",
    "sum",
    "sumMap",
    "sumMapState",
    "min",
    "minMap",
    "minMapState",
    "max",
    "maxMap",
    "maxMapState",
    "avg",
    "avgState",
    "avgMap",
    "avgMapState",
    "median",
    "uniq",
    "uniqState",
    "uniqMap",
    "uniqMapState",
}

# TODO: Make the below details part of function meta
# Functions where we use a -OrNull variant by default
ADD_OR_NULL_DATETIME_FUNCTIONS = (
    "toDateTime",
    "toDateTimeUS",
    "parseDateTime",
    "parseDateTimeBestEffort",
)

# Functions where the first argument needs to be DateTime and not DateTime64
FIRST_ARG_DATETIME_FUNCTIONS = (
    "tumble",
    "tumbleStart",
    "tumbleEnd",
    "hop",
    "hopStart",
    "hopEnd",
)

# Array-returning functions, mapped to the argument position holding the string they parse.
# ClickHouse refuses to build an array inside a Nullable ("Nested type Array(String) cannot be inside Nullable type"),
# so a Nullable input makes the whole query fail at planning time. Property reads are Nullable — a materialized column
# is scrubbed with nullIf, a JSON extract yields NULL for a missing key — so idioms like
# `splitByChar('@', properties.email)` need that argument coerced to non-Nullable before it reaches the function.
# Only the parsed string is listed: separators, patterns and lengths have to be constants in ClickHouse.
ARRAY_RESULT_FUNCTION_STRING_ARG: dict[str, int] = {
    "splitByChar": 1,
    "splitByString": 1,
    "splitByRegexp": 1,
    "splitByWhitespace": 0,
    "splitByNonAlpha": 0,
    "alphaTokens": 0,
    "tokens": 0,
    "ngrams": 0,
    "extractAll": 0,
    "extractGroups": 0,
    "extractAllGroups": 0,
    "extractAllGroupsHorizontal": 0,
    "extractAllGroupsVertical": 0,
    "extractURLParameters": 0,
    "extractURLParameterNames": 0,
    "URLHierarchy": 0,
    "URLPathHierarchy": 0,
    "JSONExtractKeys": 0,
    "JSONExtractArrayRaw": 0,
    "JSONExtractKeysAndValues": 0,
    "JSONExtractKeysAndValuesRaw": 0,
}
