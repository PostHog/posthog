from posthog.hogql.ast import ArrayType, BooleanType, DateTimeType, DateType, DecimalType, IntegerType, StringType

from .core import HogQLFunctionMeta

HOGQL_POSTHOG_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "matchesAction": HogQLFunctionMeta("matchesAction", 1, 1),
    "sparkline": HogQLFunctionMeta("sparkline", 1, 1),
    "recordingButton": HogQLFunctionMeta("recordingButton", 1, 2),
    "explainCSPReport": HogQLFunctionMeta("explainCSPReport", 1, 1),
    # Allow case-insensitive matching since people might not know "SemVer" is the right capitalization.
    # The regex strictly validates X.Y.Z with no leading zeros (matching the Rust `semver` crate
    # used for flag evaluation), optionally prefixed with 'v' and optionally suffixed with a
    # pre-release or build identifier. Invalid input falls out of `extract` as an empty string;
    # `splitByChar('.', '')` yields `['']`, and `toInt64OrNull('')` yields `NULL`, so the result
    # is `[NULL]` — `Array(Nullable(Int64))`, which ClickHouse allows (unlike the otherwise-tempting
    # `Nullable(Array(...))`). Any element-wise comparison with a NULL element evaluates to NULL,
    # which is falsy in WHERE, so invalid versions are excluded from semver comparison filters —
    # mirroring how Rust treats an unparseable version as a non-match.
    "sortablesemver": HogQLFunctionMeta(
        "arrayMap(x -> toInt64OrNull(x), splitByChar('.', extract(assumeNotNull({}), '^\\\\s*v?((0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*))(?:[-+][^\\\\s]*)?\\\\s*$')))",
        1,
        1,
        case_sensitive=False,
        signatures=[((StringType(),), ArrayType(item_type=IntegerType()))],
    ),
    "embedText": HogQLFunctionMeta("embedText", 1, 2),
    # posthog/models/channel_type/sql.py and posthog/hogql/database/schema/channel_type.py
    "lookupDomainType": HogQLFunctionMeta("lookupDomainType", 1, 1),
    "lookupPaidSourceType": HogQLFunctionMeta("lookupPaidSourceType", 1, 1),
    "lookupPaidMediumType": HogQLFunctionMeta("lookupPaidMediumType", 1, 1),
    "lookupOrganicSourceType": HogQLFunctionMeta("lookupOrganicSourceType", 1, 1),
    "lookupOrganicMediumType": HogQLFunctionMeta("lookupOrganicMediumType", 1, 1),
    # posthog/models/exchange_rate/sql.py
    # convertCurrency(from_currency, to_currency, amount, timestamp?)
    "convertCurrency": HogQLFunctionMeta(
        "convertCurrency",
        3,
        4,
        signatures=[
            (
                (
                    StringType(),
                    StringType(),
                    DecimalType(),
                ),
                DecimalType(),
            ),
            (
                (
                    StringType(),
                    StringType(),
                    DecimalType(),
                    DateType(),
                ),
                DecimalType(),
            ),
            (
                (
                    StringType(),
                    StringType(),
                    DecimalType(),
                    DateTimeType(),
                ),
                DecimalType(),
            ),
        ],
    ),
    # survey functions
    "getSurveyResponse": HogQLFunctionMeta(
        "getSurveyResponse", 1, 3, signatures=[((IntegerType(), StringType(), BooleanType()), StringType())]
    ),
    "uniqueSurveySubmissionsFilter": HogQLFunctionMeta(
        "uniqueSurveySubmissionsFilter",
        1,
        3,
        signatures=[
            ((StringType(),), StringType()),
            ((StringType(), StringType()), StringType()),
            ((StringType(), DateTimeType()), StringType()),
            ((StringType(), StringType(), StringType()), StringType()),
            ((StringType(), StringType(), DateTimeType()), StringType()),
            ((StringType(), DateTimeType(), StringType()), StringType()),
            ((StringType(), DateTimeType(), DateTimeType()), StringType()),
        ],
    ),
    # traffic type classification functions (experimental)
    "__preview_getTrafficType": HogQLFunctionMeta(
        "__preview_getTrafficType", 1, 1, signatures=[((StringType(),), StringType())]
    ),
    "__preview_getTrafficCategory": HogQLFunctionMeta(
        "__preview_getTrafficCategory", 1, 1, signatures=[((StringType(),), StringType())]
    ),
    "__preview_isBot": HogQLFunctionMeta("__preview_isBot", 1, 1, signatures=[((StringType(),), BooleanType())]),
    "__preview_getBotType": HogQLFunctionMeta(
        "__preview_getBotType", 1, 1, signatures=[((StringType(),), StringType())]
    ),
    "__preview_getBotName": HogQLFunctionMeta(
        "__preview_getBotName", 1, 1, signatures=[((StringType(),), StringType())]
    ),
    "__preview_getBotOperator": HogQLFunctionMeta(
        "__preview_getBotOperator", 1, 1, signatures=[((StringType(),), StringType())]
    ),
}
