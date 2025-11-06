from posthog.hogql.ast import DateTimeType, DateType, FloatType, IntegerType, IntervalType, StringType
from posthog.hogql.base import UnknownType

from ..core import HogQLFunctionMeta

# dates and times
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
DATETIME_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "timeZoneOf": HogQLFunctionMeta("timeZoneOf", 1, 1),
    "timeZoneOffset": HogQLFunctionMeta("timeZoneOffset", 1, 1),
    "toYear": HogQLFunctionMeta("toYear", 1, 1),
    "toQuarter": HogQLFunctionMeta("toQuarter", 1, 1),
    "toMonth": HogQLFunctionMeta("toMonth", 1, 1),
    "toDayOfYear": HogQLFunctionMeta("toDayOfYear", 1, 1),
    "toDayOfMonth": HogQLFunctionMeta("toDayOfMonth", 1, 1),
    "toDayOfWeek": HogQLFunctionMeta("toDayOfWeek", 1, 3),
    "toHour": HogQLFunctionMeta("toHour", 1, 1),
    "toMinute": HogQLFunctionMeta("toMinute", 1, 1),
    "toSecond": HogQLFunctionMeta("toSecond", 1, 1),
    "toUnixTimestamp": HogQLFunctionMeta("toUnixTimestamp", 1, 2),
    "toUnixTimestamp64Milli": HogQLFunctionMeta("toUnixTimestamp64Milli", 1, 1),
    "fromUnixTimestamp64Milli": HogQLFunctionMeta("fromUnixTimestamp64Milli", 1, 1),
    "toStartOfInterval": HogQLFunctionMeta(
        "toStartOfInterval",
        2,
        3,
        signatures=[
            ((DateTimeType(), IntervalType()), DateTimeType()),
            ((DateTimeType(), IntervalType(), DateTimeType()), DateTimeType()),
        ],
    ),
    "toStartOfYear": HogQLFunctionMeta("toStartOfYear", 1, 1),
    "toStartOfISOYear": HogQLFunctionMeta("toStartOfISOYear", 1, 1),
    "toStartOfQuarter": HogQLFunctionMeta("toStartOfQuarter", 1, 1),
    "toStartOfMonth": HogQLFunctionMeta(
        "toStartOfMonth",
        1,
        1,
        signatures=[
            ((UnknownType(),), DateType()),
        ],
    ),
    "toLastDayOfMonth": HogQLFunctionMeta("toLastDayOfMonth", 1, 1),
    "toMonday": HogQLFunctionMeta("toMonday", 1, 1),
    "toStartOfWeek": HogQLFunctionMeta(
        "toStartOfWeek",
        1,
        2,
        signatures=[
            ((UnknownType(),), DateType()),
            ((UnknownType(), UnknownType()), DateType()),
        ],
    ),
    "toStartOfDay": HogQLFunctionMeta(
        "toStartOfDay",
        1,
        2,
        signatures=[
            ((UnknownType(),), DateTimeType()),
            ((UnknownType(), UnknownType()), DateTimeType()),
        ],
    ),
    "toLastDayOfWeek": HogQLFunctionMeta("toLastDayOfWeek", 1, 2),
    "toStartOfHour": HogQLFunctionMeta(
        "toStartOfHour",
        1,
        1,
        signatures=[
            ((UnknownType(),), DateTimeType()),
        ],
    ),
    "toStartOfMinute": HogQLFunctionMeta(
        "toStartOfMinute",
        1,
        1,
        signatures=[
            ((UnknownType(),), DateTimeType()),
        ],
    ),
    "toStartOfSecond": HogQLFunctionMeta(
        "toStartOfSecond",
        1,
        1,
        signatures=[
            ((UnknownType(),), DateTimeType()),
        ],
    ),
    "toStartOfFiveMinutes": HogQLFunctionMeta("toStartOfFiveMinutes", 1, 1),
    "toStartOfTenMinutes": HogQLFunctionMeta("toStartOfTenMinutes", 1, 1),
    "toStartOfFifteenMinutes": HogQLFunctionMeta("toStartOfFifteenMinutes", 1, 1),
    "toTime": HogQLFunctionMeta("toTime", 1, 1),
    "toISOYear": HogQLFunctionMeta("toISOYear", 1, 1),
    "toISOWeek": HogQLFunctionMeta("toISOWeek", 1, 1),
    "toWeek": HogQLFunctionMeta("toWeek", 1, 3),
    "toYearWeek": HogQLFunctionMeta("toYearWeek", 1, 3),
    "age": HogQLFunctionMeta("age", 3, 3),
    "dateAdd": HogQLFunctionMeta(
        "dateAdd",
        2,
        3,
        signatures=[
            ((DateType(), UnknownType()), DateType()),
            ((StringType(), UnknownType(), DateType()), DateType()),
        ],
    ),
    "dateSub": HogQLFunctionMeta(
        "dateSub",
        2,
        3,
        signatures=[
            ((DateType(), UnknownType()), DateType()),
            ((StringType(), UnknownType(), DateType()), DateType()),
        ],
    ),
    "date_bin": HogQLFunctionMeta(
        "toStartOfInterval({1}, {0}, {2})",
        3,
        3,
        tz_aware=True,
        signatures=[
            ((IntervalType(), DateTimeType(), DateTimeType()), DateTimeType()),
        ],
        using_placeholder_arguments=True,
        using_positional_arguments=True,
    ),
    "date_add": HogQLFunctionMeta(
        "date_add",
        2,
        2,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), IntervalType()), DateTimeType()),
        ],
    ),
    "date_subtract": HogQLFunctionMeta(
        "date_sub",
        2,
        2,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), IntervalType()), DateTimeType()),
        ],
    ),
    **{
        name: HogQLFunctionMeta(
            "dateDiff",
            3,
            3,
            signatures=[
                ((StringType(), DateTimeType(), DateTimeType()), IntegerType()),
            ],
        )
        for name in ["date_diff", "dateDiff"]
    },
    "timeStampAdd": HogQLFunctionMeta("timeStampAdd", 2, 2),
    "timeStampSub": HogQLFunctionMeta("timeStampSub", 2, 2),
    "nowInBlock": HogQLFunctionMeta("nowInBlock", 1, 1),
    "rowNumberInBlock": HogQLFunctionMeta("rowNumberInBlock", 0, 0),
    "rowNumberInAllBlocks": HogQLFunctionMeta("rowNumberInAllBlocks", 0, 0),
    "timeSlot": HogQLFunctionMeta("timeSlot", 1, 1),
    "toYYYYMM": HogQLFunctionMeta("toYYYYMM", 1, 1),
    "toYYYYMMDD": HogQLFunctionMeta("toYYYYMMDD", 1, 1),
    "toYYYYMMDDhhmmss": HogQLFunctionMeta("toYYYYMMDDhhmmss", 1, 1),
    "addYears": HogQLFunctionMeta("addYears", 2, 2),
    "addMonths": HogQLFunctionMeta("addMonths", 2, 2),
    "addWeeks": HogQLFunctionMeta("addWeeks", 2, 2),
    "addDays": HogQLFunctionMeta(
        "addDays",
        2,
        2,
        signatures=[
            ((DateType(), IntegerType()), DateType()),
            ((DateType(), FloatType()), DateType()),
            ((DateTimeType(), IntegerType()), DateTimeType()),
            ((DateTimeType(), FloatType()), DateTimeType()),
        ],
    ),
    "addHours": HogQLFunctionMeta("addHours", 2, 2),
    "addMinutes": HogQLFunctionMeta("addMinutes", 2, 2),
    "addSeconds": HogQLFunctionMeta("addSeconds", 2, 2),
    "addQuarters": HogQLFunctionMeta("addQuarters", 2, 2),
    "subtractYears": HogQLFunctionMeta("subtractYears", 2, 2),
    "subtractMonths": HogQLFunctionMeta("subtractMonths", 2, 2),
    "subtractWeeks": HogQLFunctionMeta("subtractWeeks", 2, 2),
    "subtractDays": HogQLFunctionMeta("subtractDays", 2, 2),
    "subtractHours": HogQLFunctionMeta("subtractHours", 2, 2),
    "subtractMinutes": HogQLFunctionMeta("subtractMinutes", 2, 2),
    "subtractSeconds": HogQLFunctionMeta("subtractSeconds", 2, 2),
    "subtractQuarters": HogQLFunctionMeta("subtractQuarters", 2, 2),
    "timeSlots": HogQLFunctionMeta("timeSlots", 2, 3),
    "formatDateTime": HogQLFunctionMeta("formatDateTime", 2, 3),
    "dateName": HogQLFunctionMeta("dateName", 2, 2),
    "monthName": HogQLFunctionMeta("monthName", 1, 1),
    "fromUnixTimestamp": HogQLFunctionMeta(
        "fromUnixTimestamp",
        1,
        1,
        signatures=[
            ((IntegerType(),), DateTimeType()),
        ],
    ),
    "toModifiedJulianDay": HogQLFunctionMeta("toModifiedJulianDayOrNull", 1, 1),
    "fromModifiedJulianDay": HogQLFunctionMeta("fromModifiedJulianDayOrNull", 1, 1),
}

# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
DATE_GENERATOR_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "now": HogQLFunctionMeta(
        "now64",
        0,
        1,
        tz_aware=True,
        case_sensitive=False,
        signatures=[
            ((), DateTimeType(nullable=False)),
            ((UnknownType(),), DateTimeType(nullable=False)),
        ],
    ),
    "yesterday": HogQLFunctionMeta(
        "yesterday",
        0,
        0,
        signatures=[
            ((), DateType(nullable=False)),
        ],
    ),
    "current_timestamp": HogQLFunctionMeta(
        "now64",
        0,
        0,
        tz_aware=True,
        signatures=[
            ((), DateTimeType(nullable=False)),
        ],
    ),
    **{
        name: HogQLFunctionMeta(
            "today",
            0,
            0,
            signatures=[
                ((), DateType(nullable=False)),
            ],
        )
        for name in ["today", "current_date"]
    },
}

# Interval functions
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
INTERVAL_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "toIntervalSecond": HogQLFunctionMeta(
        "toIntervalSecond",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalMinute": HogQLFunctionMeta(
        "toIntervalMinute",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalHour": HogQLFunctionMeta(
        "toIntervalHour",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalDay": HogQLFunctionMeta(
        "toIntervalDay",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalWeek": HogQLFunctionMeta(
        "toIntervalWeek",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalMonth": HogQLFunctionMeta(
        "toIntervalMonth",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalQuarter": HogQLFunctionMeta(
        "toIntervalQuarter",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
    "toIntervalYear": HogQLFunctionMeta(
        "toIntervalYear",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntervalType()),
        ],
    ),
}

# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
POSTGRESQL_DATETIME_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    # PostgreSQL-style date/time functions
    "date_part": HogQLFunctionMeta(
        "if({0} = 'year', toYear({1}), if({0} = 'month', toMonth({1}), if({0} = 'day', toDayOfMonth({1}), if({0} = 'hour', toHour({1}), if({0} = 'minute', toMinute({1}), if({0} = 'second', toSecond({1}), if({0} = 'dow', toDayOfWeek({1}), if({0} = 'doy', toDayOfYear({1}), if({0} = 'quarter', toQuarter({1}), null)))))))))",
        # Maps to same implementation as extract
        2,
        2,
        signatures=[
            ((StringType(), DateTimeType()), IntegerType()),
            ((StringType(), DateType()), IntegerType()),
        ],
        using_placeholder_arguments=True,
        using_positional_arguments=True,
    ),
    **{
        name: HogQLFunctionMeta(
            "dateTrunc",
            2,
            3,  # Allow optional timezone parameter
            signatures=[
                ((StringType(), DateTimeType()), DateTimeType()),
                ((StringType(), DateTimeType(), StringType()), DateTimeType()),
            ],
        )
        for name in ["date_trunc", "dateTrunc"]
    },
    "to_timestamp": HogQLFunctionMeta(
        "toDateTime(fromUnixTimestamp({}))",
        1,
        2,
        tz_aware=True,
        signatures=[
            ((IntegerType(),), DateTimeType()),
            ((FloatType(),), DateTimeType()),
        ],
        using_placeholder_arguments=True,
    ),
    "to_char": HogQLFunctionMeta(
        "formatDateTime",
        2,
        3,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), StringType()), StringType()),
            ((DateTimeType(), StringType(), StringType()), StringType()),
        ],
    ),
    "make_timestamp": HogQLFunctionMeta(
        "makeDateTime",
        6,
        7,
        tz_aware=True,
        signatures=[
            ((IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType(), FloatType()), DateTimeType()),
            (
                (IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType(), FloatType(), StringType()),
                DateTimeType(),
            ),
        ],
    ),
    "make_date": HogQLFunctionMeta(
        "makeDate",
        3,
        3,
        signatures=[
            ((IntegerType(), IntegerType(), IntegerType()), DateType()),
        ],
    ),
    "date_bin": HogQLFunctionMeta(
        "toStartOfInterval({1}, {0}, {2})",
        3,
        3,
        tz_aware=True,
        signatures=[
            ((IntervalType(), DateTimeType(), DateTimeType()), DateTimeType()),
        ],
        using_placeholder_arguments=True,
        using_positional_arguments=True,
    ),
    "date_add": HogQLFunctionMeta(
        "date_add",
        2,
        2,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), IntervalType()), DateTimeType()),
        ],
    ),
    "date_subtract": HogQLFunctionMeta(
        "date_sub",
        2,
        2,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), IntervalType()), DateTimeType()),
        ],
    ),
    **{
        name: HogQLFunctionMeta(
            "dateDiff",
            3,
            3,
            signatures=[
                ((StringType(), DateTimeType(), DateTimeType()), IntegerType()),
            ],
        )
        for name in ["date_diff", "dateDiff"]
    },
    "make_interval": HogQLFunctionMeta(
        "toIntervalYear({}) + toIntervalMonth({}) + toIntervalDay({}) + toIntervalHour({}) + toIntervalMinute({}) + toIntervalSecond({})",
        # Changed from makeInterval to addInterval
        6,
        6,
        signatures=[
            (
                (IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType()),
                DateTimeType(),
            ),
        ],
        using_placeholder_arguments=True,
    ),
    # Clickhouse doesn't have a TIME type, so this would be the alternative
    # "make_time": HogQLFunctionMeta(
    #     "toTime(makeDateTime(1970, 1, 1, {}, {}, {}))",
    #     3,
    #     3,
    #     signatures=[((IntegerType(), IntegerType(), FloatType()), DateTimeType())],
    # ),
    "make_timestamptz": HogQLFunctionMeta(
        "toTimeZone(makeDateTime({}, {}, {}, {}, {}, {}), {})",
        7,
        7,
        signatures=[
            (
                (IntegerType(), IntegerType(), IntegerType(), IntegerType(), IntegerType(), FloatType(), StringType()),
                DateTimeType(),
            ),
        ],
        tz_aware=True,
        using_placeholder_arguments=True,
    ),
    "timezone": HogQLFunctionMeta(
        "toTimeZone({1}, {0})",
        2,
        2,
        signatures=[((StringType(), DateTimeType()), DateTimeType())],
        tz_aware=True,
        using_placeholder_arguments=True,
        using_positional_arguments=True,
    ),
    "toTimeZone": HogQLFunctionMeta(
        "toTimeZone",
        1,
        2,
        tz_aware=True,
        signatures=[
            ((DateTimeType(), StringType()), DateTimeType()),
        ],
    ),
}

# Combined datetime functions
DATETIME_AND_INTERVAL_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    **DATETIME_FUNCTIONS,
    **INTERVAL_FUNCTIONS,
    **DATE_GENERATOR_FUNCTIONS,
    **POSTGRESQL_DATETIME_FUNCTIONS,
}
