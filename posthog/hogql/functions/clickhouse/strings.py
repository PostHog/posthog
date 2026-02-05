from posthog.hogql.ast import IntegerType, StringType

from ..core import HogQLFunctionMeta

# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
STRING_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "left": HogQLFunctionMeta("left", 2, 2, signatures=[((StringType(), IntegerType()), StringType())]),
    "right": HogQLFunctionMeta("right", 2, 2, signatures=[((StringType(), IntegerType()), StringType())]),
    "lengthUTF8": HogQLFunctionMeta("lengthUTF8", 1, 1),
    "leftPad": HogQLFunctionMeta("leftPad", 2, 3),
    "rightPad": HogQLFunctionMeta("rightPad", 2, 3),
    "leftPadUTF8": HogQLFunctionMeta("leftPadUTF8", 2, 3),
    "rightPadUTF8": HogQLFunctionMeta("rightPadUTF8", 2, 3),
    "lower": HogQLFunctionMeta("lower", 1, 1, case_sensitive=False),
    "upper": HogQLFunctionMeta("upper", 1, 1, case_sensitive=False),
    "lowerUTF8": HogQLFunctionMeta("lowerUTF8", 1, 1),
    "upperUTF8": HogQLFunctionMeta("upperUTF8", 1, 1),
    "isValidUTF8": HogQLFunctionMeta("isValidUTF8", 1, 1),
    "toValidUTF8": HogQLFunctionMeta("toValidUTF8", 1, 1),
    "format": HogQLFunctionMeta("format", 2, None),
    "reverseUTF8": HogQLFunctionMeta("reverseUTF8", 1, 1),
    "concat": HogQLFunctionMeta("concat", 2, None, case_sensitive=False),
    "substring": HogQLFunctionMeta("substring", 3, 3, case_sensitive=False),
    "substringUTF8": HogQLFunctionMeta("substringUTF8", 3, 3),
    "appendTrailingCharIfAbsent": HogQLFunctionMeta("appendTrailingCharIfAbsent", 2, 2),
    "convertCharset": HogQLFunctionMeta("convertCharset", 3, 3),
    "base58Encode": HogQLFunctionMeta("base58Encode", 1, 1),
    "base58Decode": HogQLFunctionMeta("base58Decode", 1, 1),
    "tryBase58Decode": HogQLFunctionMeta("tryBase58Decode", 1, 1),
    "base64Encode": HogQLFunctionMeta("base64Encode", 1, 1),
    "base64Decode": HogQLFunctionMeta("base64Decode", 1, 1),
    "tryBase64Decode": HogQLFunctionMeta("tryBase64Decode", 1, 1),
    "endsWith": HogQLFunctionMeta("endsWith", 2, 2),
    "startsWith": HogQLFunctionMeta("startsWith", 2, 2),
    "encodeXMLComponent": HogQLFunctionMeta("encodeXMLComponent", 1, 1),
    "decodeXMLComponent": HogQLFunctionMeta("decodeXMLComponent", 1, 1),
    "extractTextFromHTML": HogQLFunctionMeta("extractTextFromHTML", 1, 1),
    "ascii": HogQLFunctionMeta("ascii", 1, 1, case_sensitive=False),
    "concatWithSeparator": HogQLFunctionMeta("concatWithSeparator", 2, None),
}

# searching in strings
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
STRING_SEARCH_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "position": HogQLFunctionMeta("position", 2, 3, case_sensitive=False),
    "positionCaseInsensitive": HogQLFunctionMeta("positionCaseInsensitive", 2, 3),
    "positionUTF8": HogQLFunctionMeta("positionUTF8", 2, 3),
    "positionCaseInsensitiveUTF8": HogQLFunctionMeta("positionCaseInsensitiveUTF8", 2, 3),
    "multiSearchAllPositions": HogQLFunctionMeta("multiSearchAllPositions", 2, 2),
    "multiSearchAllPositionsUTF8": HogQLFunctionMeta("multiSearchAllPositionsUTF8", 2, 2),
    "multiSearchFirstPosition": HogQLFunctionMeta("multiSearchFirstPosition", 2, 2),
    "multiSearchFirstIndex": HogQLFunctionMeta("multiSearchFirstIndex", 2, 2),
    "multiSearchAny": HogQLFunctionMeta("multiSearchAny", 2, 2),
    "multiSearchAllPositionsCaseInsensitive": HogQLFunctionMeta("multiSearchAllPositionsCaseInsensitive", 2, 2),
    "multiSearchAllPositionsCaseInsensitiveUTF8": HogQLFunctionMeta("multiSearchAllPositionsCaseInsensitiveUTF8", 2, 2),
    "multiSearchAnyUTF8": HogQLFunctionMeta("multiSearchAnyUTF8", 2, 2),
    "multiSearchAnyCaseInsensitive": HogQLFunctionMeta("multiSearchAnyCaseInsensitive", 2, 2),
    "multiSearchAnyCaseInsensitiveUTF8": HogQLFunctionMeta("multiSearchAnyCaseInsensitiveUTF8", 2, 2),
    "multiSearchFirstIndexUTF8": HogQLFunctionMeta("multiSearchFirstIndexUTF8", 2, 2),
    "multiSearchFirstIndexCaseInsensitive": HogQLFunctionMeta("multiSearchFirstIndexCaseInsensitive", 2, 2),
    "multiSearchFirstIndexCaseInsensitiveUTF8": HogQLFunctionMeta("multiSearchFirstIndexCaseInsensitiveUTF8", 2, 2),
    "multiSearchFirstPositionUTF8": HogQLFunctionMeta("multiSearchFirstPositionUTF8", 2, 2),
    "multiSearchFirstPositionCaseInsensitive": HogQLFunctionMeta("multiSearchFirstPositionCaseInsensitive", 2, 2),
    "multiSearchFirstPositionCaseInsensitiveUTF8": HogQLFunctionMeta(
        "multiSearchFirstPositionCaseInsensitiveUTF8", 2, 2
    ),
    "match": HogQLFunctionMeta("match", 2, 2),
    "multiMatchAny": HogQLFunctionMeta("multiMatchAny", 2, 2),
    "multiMatchAnyIndex": HogQLFunctionMeta("multiMatchAnyIndex", 2, 2),
    "multiMatchAllIndices": HogQLFunctionMeta("multiMatchAllIndices", 2, 2),
    "multiFuzzyMatchAny": HogQLFunctionMeta("multiFuzzyMatchAny", 3, 3),
    "multiFuzzyMatchAnyIndex": HogQLFunctionMeta("multiFuzzyMatchAnyIndex", 3, 3),
    "multiFuzzyMatchAllIndices": HogQLFunctionMeta("multiFuzzyMatchAllIndices", 3, 3),
    "extract": HogQLFunctionMeta("extract", 2, 2, case_sensitive=False),
    "extractAll": HogQLFunctionMeta("extractAll", 2, 2),
    "extractAllGroupsHorizontal": HogQLFunctionMeta("extractAllGroupsHorizontal", 2, 2),
    "extractAllGroupsVertical": HogQLFunctionMeta("extractAllGroupsVertical", 2, 2),
    "extractGroups": HogQLFunctionMeta("extractGroups", 2, 2),
    "like": HogQLFunctionMeta("like", 2, 2),
    "ilike": HogQLFunctionMeta("ilike", 2, 2),
    "notLike": HogQLFunctionMeta("notLike", 2, 2),
    "notILike": HogQLFunctionMeta("notILike", 2, 2),
    "locate": HogQLFunctionMeta("locate", 2, 3),
    "ngramDistance": HogQLFunctionMeta("ngramDistance", 2, 2),
    "ngramDistanceCaseInsensitive": HogQLFunctionMeta("ngramDistanceCaseInsensitive", 2, 2),
    "ngramDistanceUTF8": HogQLFunctionMeta("ngramDistanceUTF8", 2, 2),
    "ngramDistanceCaseInsensitiveUTF8": HogQLFunctionMeta("ngramDistanceCaseInsensitiveUTF8", 2, 2),
    "ngramSearch": HogQLFunctionMeta("ngramSearch", 2, 2),
    "ngramSearchCaseInsensitive": HogQLFunctionMeta("ngramSearchCaseInsensitive", 2, 2),
    "ngramSearchUTF8": HogQLFunctionMeta("ngramSearchUTF8", 2, 2),
    "ngramSearchCaseInsensitiveUTF8": HogQLFunctionMeta("ngramSearchCaseInsensitiveUTF8", 2, 2),
    "countSubstrings": HogQLFunctionMeta("countSubstrings", 2, 3),
    "countSubstringsCaseInsensitive": HogQLFunctionMeta("countSubstringsCaseInsensitive", 2, 3),
    "countSubstringsCaseInsensitiveUTF8": HogQLFunctionMeta("countSubstringsCaseInsensitiveUTF8", 2, 3),
    "countMatches": HogQLFunctionMeta("countMatches", 2, 2),
    "countMatchesCaseInsensitive": HogQLFunctionMeta("countMatchesCaseInsensitive", 2, 2),
    "hasSubsequence": HogQLFunctionMeta("hasSubsequence", 2, 2),
    "hasSubsequenceCaseInsensitive": HogQLFunctionMeta("hasSubsequenceCaseInsensitive", 2, 2),
    "hasSubsequenceUTF8": HogQLFunctionMeta("hasSubsequenceUTF8", 2, 2),
    "hasSubsequenceCaseInsensitiveUTF8": HogQLFunctionMeta("hasSubsequenceCaseInsensitiveUTF8", 2, 2),
    "hasToken": HogQLFunctionMeta("hasToken", 2, 2),
    "hasTokenCaseInsensitive": HogQLFunctionMeta("hasTokenCaseInsensitive", 2, 2),
    "hasTokenOrNull": HogQLFunctionMeta("hasTokenOrNull", 2, 2),
    "hasTokenCaseInsensitiveOrNull": HogQLFunctionMeta("hasTokenCaseInsensitiveOrNull", 2, 2),
    "hasAllTokens": HogQLFunctionMeta("hasAllTokens", 2, 2),
    "hasAnyTokens": HogQLFunctionMeta("hasAnyTokens", 2, 2),
    "regexpExtract": HogQLFunctionMeta("regexpExtract", 2, 3),
}

# replacing in strings
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
STRING_REPLACE_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "replace": HogQLFunctionMeta("replace", 3, 3, case_sensitive=False),
    "replaceAll": HogQLFunctionMeta("replaceAll", 3, 3),
    "replaceOne": HogQLFunctionMeta("replaceOne", 3, 3),
    "replaceRegexpAll": HogQLFunctionMeta("replaceRegexpAll", 3, 3),
    "replaceRegexpOne": HogQLFunctionMeta("replaceRegexpOne", 3, 3),
    "regexpQuoteMeta": HogQLFunctionMeta("regexpQuoteMeta", 1, 1),
    "translate": HogQLFunctionMeta("translate", 3, 3),
    "translateUTF8": HogQLFunctionMeta("translateUTF8", 3, 3),
}

# splitting strings
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
STRING_SPLIT_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "splitByChar": HogQLFunctionMeta("splitByChar", 2, 3),
    "splitByString": HogQLFunctionMeta("splitByString", 2, 3),
    "splitByRegexp": HogQLFunctionMeta("splitByRegexp", 2, 3),
    "splitByWhitespace": HogQLFunctionMeta("splitByWhitespace", 1, 2),
    "splitByNonAlpha": HogQLFunctionMeta("splitByNonAlpha", 1, 2),
    "alphaTokens": HogQLFunctionMeta("alphaTokens", 1, 2),
    "extractAllGroups": HogQLFunctionMeta("extractAllGroups", 2, 2),
    "ngrams": HogQLFunctionMeta("ngrams", 2, 2),
    "tokens": HogQLFunctionMeta("tokens", 1, 1),
}

# PostgreSQL-style string functions
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
POSTGRESQL_STRING_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "repeat": HogQLFunctionMeta(
        "repeat",
        2,
        2,
        signatures=[((StringType(), IntegerType()), StringType())],
    ),
    "initcap": HogQLFunctionMeta(
        "initcap",
        1,
        1,
        signatures=[((StringType(),), StringType())],
    ),
    "lpad": HogQLFunctionMeta(
        "lpad",
        3,
        3,
        signatures=[((StringType(), IntegerType(), StringType()), StringType())],
    ),
    "rpad": HogQLFunctionMeta(
        "rpad",
        3,
        3,
        signatures=[((StringType(), IntegerType(), StringType()), StringType())],
    ),
    "split_part": HogQLFunctionMeta(
        # We need to repeat each argument in the format string since we use each one multiple times
        "if(empty(splitByString({1}, {0})), '', if(length(splitByString({1}, {0})) >= {2}, arrayElement(splitByString({1}, {0}), {2}), ''))",
        3,
        3,
        signatures=[((StringType(), StringType(), IntegerType()), StringType())],
        using_placeholder_arguments=True,
        using_positional_arguments=True,
    ),
}

# PostgreSQL trim functions - using dictionary comprehensions like in the original
# Keep in sync with the posthog.com repository: contents/docs/sql/clickhouse-functions.mdx
POSTGRESQL_TRIM_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    **{
        name: HogQLFunctionMeta(
            "trimLeft",
            1,
            2,
            signatures=[
                ((StringType(),), StringType()),
                ((StringType(), StringType()), StringType()),
            ],
        )
        for name in ["ltrim", "trimLeft"]
    },
    **{
        name: HogQLFunctionMeta(
            "trimRight",
            1,
            2,
            signatures=[
                ((StringType(),), StringType()),
                ((StringType(), StringType()), StringType()),
            ],
        )
        for name in ["rtrim", "trimRight"]
    },
    **{
        name: HogQLFunctionMeta(
            "trim",
            1,
            2,
            signatures=[
                ((StringType(),), StringType()),
                ((StringType(), StringType()), StringType()),
            ],
            case_sensitive=False,
        )
        for name in ["btrim", "trim"]
    },
}

# Combined strings functions
STRINGS_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    **STRING_FUNCTIONS,
    **STRING_SEARCH_FUNCTIONS,
    **STRING_REPLACE_FUNCTIONS,
    **STRING_SPLIT_FUNCTIONS,
    **POSTGRESQL_STRING_FUNCTIONS,
    **POSTGRESQL_TRIM_FUNCTIONS,
}
