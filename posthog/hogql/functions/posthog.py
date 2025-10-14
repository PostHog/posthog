from posthog.hogql.ast import BooleanType, Constant, DateTimeType, DateType, DecimalType, IntegerType, StringType
from posthog.hogql.language_mappings import LANGUAGE_CODES, LANGUAGE_NAMES

from .core import HogQLFunctionMeta

HOGQL_POSTHOG_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "matchesAction": HogQLFunctionMeta("matchesAction", 1, 1),
    "sparkline": HogQLFunctionMeta("sparkline", 1, 1),
    "recording_button": HogQLFunctionMeta("recording_button", 1, 2),
    "explain_csp_report": HogQLFunctionMeta("explain_csp_report", 1, 1),
    # Allow case-insensitive matching since people might not know "SemVer" is the right capitalization
    "sortablesemver": HogQLFunctionMeta("sortableSemVer", 1, 1, case_sensitive=False),
    # posthog/models/channel_type/sql.py and posthog/hogql/database/schema/channel_type.py
    "hogql_lookupDomainType": HogQLFunctionMeta("hogql_lookupDomainType", 1, 1),
    "hogql_lookupPaidSourceType": HogQLFunctionMeta("hogql_lookupPaidSourceType", 1, 1),
    "hogql_lookupPaidMediumType": HogQLFunctionMeta("hogql_lookupPaidMediumType", 1, 1),
    "hogql_lookupOrganicSourceType": HogQLFunctionMeta("hogql_lookupOrganicSourceType", 1, 1),
    "hogql_lookupOrganicMediumType": HogQLFunctionMeta("hogql_lookupOrganicMediumType", 1, 1),
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
    # Translates languages codes to full language name
    "languageCodeToName": HogQLFunctionMeta(
        clickhouse_name="transform",
        min_args=1,
        max_args=1,
        suffix_args=[
            Constant(value=LANGUAGE_CODES),
            Constant(value=LANGUAGE_NAMES),
            Constant(value="Unknown"),
        ],
        signatures=[((StringType(),), StringType())],
    ),
}
