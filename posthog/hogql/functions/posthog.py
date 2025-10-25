from posthog.hogql.ast import ArrayType, BooleanType, DateTimeType, DateType, DecimalType, IntegerType, StringType

from .core import HogQLFunctionMeta

HOGQL_POSTHOG_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "matchesAction": HogQLFunctionMeta("matchesAction", 1, 1),
    "sparkline": HogQLFunctionMeta("sparkline", 1, 1),
    "recordingButton": HogQLFunctionMeta("recordingButton", 1, 2),
    "explainCSPReport": HogQLFunctionMeta("explainCSPReport", 1, 1),
    # Allow case-insensitive matching since people might not know "SemVer" is the right capitalization
    "sortablesemver": HogQLFunctionMeta(
        "arrayMap(x -> toInt64OrZero(x),  splitByChar('.', extract(assumeNotNull({}), '(\\d+(\\.\\d+)+)')))",
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
        "uniqueSurveySubmissionsFilter", 1, 1, signatures=[((StringType(),), StringType())]
    ),
}
