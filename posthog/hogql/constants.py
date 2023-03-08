# HogQL -> ClickHouse allowed transformations
CLICKHOUSE_FUNCTIONS = {
    # arithmetic
    "abs": "abs",
    "max2": "max2",
    "min2": "min2",
    # type conversions
    "toInt": "toInt64OrNull",
    "toFloat": "toFloat64OrNull",
    "toDecimal": "toDecimal64OrNull",
    "toDate": "toDateOrNull",
    "toDateTime": "parseDateTimeBestEffort",
    "toIntervalSecond": "toIntervalSecond",
    "toIntervalMinute": "toIntervalMinute",
    "toIntervalHour": "toIntervalHour",
    "toIntervalDay": "toIntervalDay",
    "toIntervalWeek": "toIntervalWeek",
    "toIntervalMonth": "toIntervalMonth",
    "toIntervalQuarter": "toIntervalQuarter",
    "toIntervalYear": "toIntervalYear",
    "toString": "toString",
    # date functions
    "now": "now",
    "NOW": "now",
    "toMonday": "toMonday",
    "toStartOfYear": "toStartOfYear",
    "toStartOfQuarter": "toStartOfQuarter",
    "toStartOfMonth": "toStartOfMonth",
    "toStartOfWeek": "toStartOfWeek",
    "toStartOfDay": "toStartOfDay",
    "toStartOfHour": "toStartOfHour",
    "toStartOfMinute": "toStartOfMinute",
    "toStartOfSecond": "toStartOfSecond",
    "toStartOfFiveMinutes": "toStartOfFiveMinutes",
    "toStartOfTenMinutes": "toStartOfTenMinutes",
    "toStartOfFifteenMinutes": "toStartOfFifteenMinutes",
    "toTimezone": "toTimezone",
    "age": "age",
    "dateDiff": "dateDiff",
    "dateTrunc": "dateTrunc",
    "formatDateTime": "formatDateTime",
    # string functions
    "length": "lengthUTF8",
    "empty": "empty",
    "notEmpty": "notEmpty",
    "leftPad": "leftPad",
    "rightPad": "rightPad",
    "lower": "lower",
    "upper": "upper",
    "repeat": "repeat",
    "format": "format",
    "concat": "concat",
    "coalesce": "coalesce",
    "substring": "substringUTF8",
    "appendTrailingCharIfAbsent": "appendTrailingCharIfAbsent",
    "endsWith": "endsWith",
    "startsWith": "startsWith",
    "trim": "trimBoth",
    "trimLeft": "trimLeft",
    "trimRight": "trimRight",
    "extractTextFromHTML": "extractTextFromHTML",
    "match": "match",
    "like": "like",
    "ilike": "ilike",
    "notLike": "notLike",
    "replace": "replace",
    "replaceOne": "replaceOne",
    # array functions
    "tuple": "tuple",
    # conditional
    "if": "if",
    "not": "not",
    "multiIf": "multiIf",
    # rounding
    "round": "round",
    "floor": "floor",
    "ceil": "ceil",
    "trunc": "trunc",
}
# Permitted HogQL aggregations
HOGQL_AGGREGATIONS = {
    "count": 0,
    "countIf": 1,
    "countDistinct": 1,
    "countDistinctIf": 2,
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
}
# Keywords passed to ClickHouse without transformation
KEYWORDS = ["true", "false", "null"]

# Keywords you can't alias to
RESERVED_KEYWORDS = KEYWORDS + ["team_id"]

# Allow-listed fields returned when you select "*" from events. Person and group fields will be nested later.
SELECT_STAR_FROM_EVENTS_FIELDS = [
    "uuid",
    "event",
    "properties",
    "timestamp",
    "team_id",
    "distinct_id",
    "elements_chain",
    "created_at",
    "person_id",
    "person.created_at",
    "person.properties",
]

# Never return more rows than this in top level HogQL SELECT statements
DEFAULT_RETURNED_ROWS = 100
MAX_SELECT_RETURNED_ROWS = 65535
