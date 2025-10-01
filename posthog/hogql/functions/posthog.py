from posthog.hogql.ast import DateTimeType, DateType, DecimalType, StringType

from .core import HogQLFunctionMeta

HOGQL_POSTHOG_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "matchesAction": HogQLFunctionMeta("matchesAction", 1, 1),
    "sparkline": HogQLFunctionMeta("sparkline", 1, 1),
    "recording_button": HogQLFunctionMeta("recording_button", 1, 2),
    "explain_csp_report": HogQLFunctionMeta("explain_csp_report", 1, 1),
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
}
