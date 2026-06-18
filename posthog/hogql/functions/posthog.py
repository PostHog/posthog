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
    # pre-release or build identifier. Invalid input falls out of `extract` as an empty string,
    # which `splitByChar` would turn into `[]` (empty) — and `[] < [1,2,3]` is true in ClickHouse,
    # which would silently include invalid versions in `< filter` queries (exactly the bug we're
    # fixing). So we substitute a sentinel `'_'` for the empty-extract case via `nullIf` +
    # `coalesce`, which `toInt64OrNull` then maps to `NULL`. Invalid input becomes `[NULL]`, type
    # `Array(Nullable(Int64))` — ClickHouse accepts this (unlike `Nullable(Array(...))`).
    # Element-wise array comparison propagates NULL through any operator (>, >=, <, <=, =, !=),
    # so invalid versions are excluded from every semver filter — matching Rust's behavior.
    "sortablesemver": HogQLFunctionMeta(
        "arrayMap(x -> toInt64OrNull(x), splitByChar('.', coalesce(nullIf(extract(assumeNotNull({}), '^\\\\s*v?((0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*))(?:[-+][^\\\\s]*)?\\\\s*$'), ''), '_')))",
        1,
        1,
        case_sensitive=False,
        signatures=[((StringType(),), ArrayType(item_type=IntegerType()))],
    ),
    "embedText": HogQLFunctionMeta("embedText", 1, 2),
    # Temporary (June 2026 MaxMind incident: https://posthog.slack.com/archives/C0B9DDSCTF1): geoip lookups against the city_postal_ip_trie ClickHouse dictionary,
    # used by posthog/hogql/transforms/geoip_dict_fallback.py and rendered in the ClickHouse printer. Remove with it.
    "_lookupGeoipCityName": HogQLFunctionMeta("_lookupGeoipCityName", 1, 1),
    "_lookupGeoipPostalCode": HogQLFunctionMeta("_lookupGeoipPostalCode", 1, 1),
    # posthog/models/channel_type/sql.py and posthog/hogql/database/schema/channel_type.py
    "lookupDomainType": HogQLFunctionMeta("lookupDomainType", 1, 1),
    "lookupPaidSourceType": HogQLFunctionMeta("lookupPaidSourceType", 1, 1),
    "lookupPaidMediumType": HogQLFunctionMeta("lookupPaidMediumType", 1, 1),
    "lookupOrganicSourceType": HogQLFunctionMeta("lookupOrganicSourceType", 1, 1),
    "lookupOrganicMediumType": HogQLFunctionMeta("lookupOrganicMediumType", 1, 1),
    # Expanded to SQL in the resolver's visit_call; these never map to a real CH function. (The
    # bot/traffic-type functions are registered further down; the resolver expands them too.)
    "_defaultChannelType": HogQLFunctionMeta("_defaultChannelType", 7, 7),
    "_domainType": HogQLFunctionMeta("_domainType", 1, 1),
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
    # Bot / traffic-type classification functions.
    "getTrafficType": HogQLFunctionMeta("getTrafficType", 1, 1, signatures=[((StringType(),), StringType())]),
    "getTrafficCategory": HogQLFunctionMeta("getTrafficCategory", 1, 1, signatures=[((StringType(),), StringType())]),
    "isLikelyBot": HogQLFunctionMeta("isLikelyBot", 1, 1, signatures=[((StringType(),), BooleanType())]),
    "getBotType": HogQLFunctionMeta("getBotType", 1, 1, signatures=[((StringType(),), StringType())]),
    "getBotName": HogQLFunctionMeta("getBotName", 1, 1, signatures=[((StringType(),), StringType())]),
    "getBotOperator": HogQLFunctionMeta("getBotOperator", 1, 1, signatures=[((StringType(),), StringType())]),
    # Deprecated __preview_* aliases — kept so ad-hoc queries written against the preview names keep working.
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
