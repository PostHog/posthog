from clickhouse_driver.errors import ServerException, UnknownTypeError
from parameterized import parameterized

from posthog.errors import (
    BAD_GET_FALLBACK_MESSAGE,
    CHQueryErrorBadGet,
    CHQueryErrorCannotParseBool,
    CHQueryErrorCannotParseUuid,
    CHQueryErrorInvalidJoinOnExpression,
    CHQueryErrorUnknownType,
    ExposedCHQueryError,
    InternalCHQueryError,
    QueryErrorCategory,
    look_up_clickhouse_error_code_meta,
    wrap_clickhouse_query_error,
)


class TestWrapClickhouseQueryError:
    @parameterized.expand(
        [
            (44, "ILLEGAL_COLUMN"),
            (50, "UNKNOWN_TYPE"),
            (59, "ILLEGAL_TYPE_OF_COLUMN_FOR_FILTER"),
            (80, "INCORRECT_QUERY"),
            (122, "INCOMPATIBLE_COLUMNS"),
            (174, "CYCLIC_ALIASES"),
            (207, "AMBIGUOUS_IDENTIFIER"),
            (211, "EMPTY_QUERY"),
            (264, "INCOMPATIBLE_TYPE_OF_JOIN"),
            (352, "AMBIGUOUS_COLUMN_NAME"),
            (377, "ILLEGAL_SYNTAX_FOR_DATA_TYPE"),
            (703, "INVALID_IDENTIFIER"),
        ]
    )
    def test_user_error_codes_wrap_as_exposed_error(self, code: int, name: str) -> None:
        err = ServerException(f"DB::Exception: {name}", code=code)

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, ExposedCHQueryError)
        assert look_up_clickhouse_error_code_meta(err).get_category() == QueryErrorCategory.USER_ERROR

    @parameterized.expand(
        [
            (
                6,
                "CANNOT_PARSE_TEXT",
                "Cannot parse a value as the requested type. Check your input formats and type conversions.",
            ),
            (38, "CANNOT_PARSE_DATE", "Cannot parse a date. Check your date values and their format."),
            (41, "CANNOT_PARSE_DATETIME", "Cannot parse a date and time. Check your datetime values and their format."),
            (69, "ARGUMENT_OUT_OF_BOUND", "An argument is out of bounds."),
            (
                70,
                "CANNOT_CONVERT_TYPE",
                "Cannot convert one type to another in the query. Check the types in your comparisons and IN clauses.",
            ),
            (
                72,
                "CANNOT_PARSE_NUMBER",
                "Cannot parse a number. Check for non-numeric values in your type conversions.",
            ),
            (
                121,
                "UNSUPPORTED_JOIN_KEYS",
                "Unsupported JOIN keys. Check the expressions and types used to join your tables.",
            ),
            (
                124,
                "INCORRECT_ELEMENT_OF_SET",
                "An element of an IN set is invalid. Make sure each tuple in the IN list has the same number "
                "of elements as the left side, and that each element is a constant.",
            ),
            (
                125,
                "INCORRECT_RESULT_OF_SCALAR_SUBQUERY",
                "A scalar subquery returned more than one row, or an empty result that cannot be nullable. "
                "Make sure the subquery returns a single value.",
            ),
            (
                128,
                "TOO_LARGE_ARRAY_SIZE",
                "An array has an invalid or unsupported size. Check array lengths and reduce the number of elements.",
            ),
            (
                130,
                "CANNOT_READ_ARRAY_FROM_TEXT",
                "Cannot parse an array. Check the format of the values converted to arrays.",
            ),
            (
                190,
                "SIZES_OF_ARRAYS_DONT_MATCH",
                "Array sizes do not match. Make sure arrays used together have the same number of elements.",
            ),
            (376, "CANNOT_PARSE_UUID", "Cannot parse a UUID. Check the format of the values converted to UUIDs."),
            (
                403,
                "INVALID_JOIN_ON_EXPRESSION",
                "Invalid JOIN ON expression. Check that the condition uses supported comparisons between the joined tables.",
            ),
            (407, "DECIMAL_OVERFLOW", "Decimal overflow while executing query."),
            (
                427,
                "CANNOT_COMPILE_REGEXP",
                "Cannot compile the regular expression. Check RE2 syntax, escaping, and the number of capturing groups.",
            ),
            (
                440,
                "INVALID_LIMIT_EXPRESSION",
                "Invalid LIMIT or OFFSET expression. Use a constant number in the supported range.",
            ),
            (467, "CANNOT_PARSE_BOOL", "Cannot parse a boolean. Check for values other than true, false, 1, or 0."),
            (
                491,
                "UNACCEPTABLE_URL",
                "PostHog can't read from this storage host. Check the files URL pattern on the table points at "
                "S3, Google Cloud Storage, Cloudflare R2, or Azure Blob Storage.",
            ),
            (675, "CANNOT_PARSE_IPV4", "Cannot parse an IPv4 address. Check the format of your IP addresses."),
            (676, "CANNOT_PARSE_IPV6", "Cannot parse an IPv6 address. Check the format of your IP addresses."),
            (
                691,
                "UNKNOWN_ELEMENT_OF_ENUM",
                "A value is not a member of the enum. Check the allowed values of the enum type.",
            ),
        ]
    )
    def test_fixed_message_codes_hide_raw_clickhouse_text(self, code: int, name: str, message: str) -> None:
        raw_message = (
            f"DB::Exception: {name}: cannot convert 'private-row-value'. "
            "While processing SELECT * FROM s3('https://example.com/private.parquet?token=fake-signed-token', "
            "'fake-access-key', 'fake-secret-key') SETTINGS custom_setting='fake-setting-secret'. "
            "Received from private-host.example.com:9000. Stack trace: private-stack-frame"
        )
        err = ServerException(raw_message, code=code, nested=ServerException("fake-nested-secret", code=1000))

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, ExposedCHQueryError)
        assert str(wrapped) == message
        assert wrapped.message == message
        assert wrapped.code == code
        assert wrapped.code_name == name.lower()
        assert wrapped.nested is None
        assert look_up_clickhouse_error_code_meta(err).get_category() == QueryErrorCategory.USER_ERROR

    @parameterized.expand(
        [
            (376, CHQueryErrorCannotParseUuid),
            (403, CHQueryErrorInvalidJoinOnExpression),
            (467, CHQueryErrorCannotParseBool),
        ]
    )
    def test_fixed_messages_preserve_importable_exception_types(
        self, code: int, error_type: type[ExposedCHQueryError]
    ) -> None:
        wrapped = wrap_clickhouse_query_error(ServerException("private-row-value", code=code))

        assert isinstance(wrapped, error_type)

    def test_bad_get_exposes_type_names_without_clickhouse_context(self) -> None:
        err = ServerException(
            "DB::Exception: Bad get: has Float64, requested UInt64. "
            "While processing private-row-value. Stack trace: private-stack-frame",
            code=170,
            nested=ServerException("fake-nested-secret", code=1000),
        )

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, CHQueryErrorBadGet)
        assert str(wrapped) == (
            "A value in the query has the wrong type: got Float64, expected UInt64. "
            "Check function parameters and type conversions."
        )
        assert "private" not in wrapped.message
        assert wrapped.code == 170
        assert wrapped.code_name == "bad_get"
        assert wrapped.nested is None
        assert look_up_clickhouse_error_code_meta(err).get_category() == QueryErrorCategory.USER_ERROR

    @parameterized.expand(
        [
            (
                "aggregate_state",
                "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))",
                "This query returns a column of type `AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))`, "
                "which PostHog can't send back in results. The column holds a stored aggregate state. Wrap it in the "
                "matching -Merge function, for example `argMinMerge(column)`, to get the final value.",
            ),
            (
                "mixed_value_types",
                "Variant(Int64, UInt64)",
                "This query returns a column of type `Variant(Int64, UInt64)`, which PostHog can't send back in "
                "results. The column mixes value types. This usually comes from `UNION ALL` branches, `coalesce()` "
                "or `ifNull()` arguments, or `if()` branches that return different types. Make them return one "
                "type, for example with `toString()` or `toFloat()`.",
            ),
            (
                "other_type",
                "JSON",
                "This query returns a column of type `JSON`, which PostHog can't send back in results. Convert the "
                "column to a basic type such as a string, number, or date, or leave it out of the results.",
            ),
        ]
    )
    def test_unreadable_result_type_names_the_fix_for_its_type(
        self, _name: str, column_type: str, expected_message: str
    ) -> None:
        wrapped = wrap_clickhouse_query_error(UnknownTypeError(f"Unknown type {column_type}"))

        assert isinstance(wrapped, CHQueryErrorUnknownType)
        assert wrapped.code_name == "unknown_type"
        assert str(wrapped) == expected_message

    def test_bad_get_hides_unrecognized_raw_message(self) -> None:
        err = ServerException(
            "DB::Exception: Bad get: has private-row-value, requested UInt64. While processing private-query-context.",
            code=170,
        )

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, CHQueryErrorBadGet)
        assert str(wrapped) == BAD_GET_FALLBACK_MESSAGE
        assert "private" not in wrapped.message

    @parameterized.expand(
        [
            # NETWORK_ERROR (210) is a genuine server-side fault and must not be exposed.
            (210, "NETWORK_ERROR"),
            # SYNTAX_ERROR (62) stays internal: HogQL validates syntax first, so a raw CH syntax error
            # signals a PostHog SQL-generation bug that belongs in error tracking.
            (62, "SYNTAX_ERROR"),
            (115, "UNKNOWN_SETTING"),
            (497, "ACCESS_DENIED"),
            (499, "S3_ERROR"),
            (516, "AUTHENTICATION_FAILED"),
            (1000, "POCO_EXCEPTION"),
            (1001, "STD_EXCEPTION"),
            (9999, "FUTURE_ERROR"),
        ]
    )
    def test_codes_stay_internal(self, code: int, name: str) -> None:
        err = ServerException(f"DB::Exception: {name}", code=code)

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, InternalCHQueryError)
        assert not isinstance(wrapped, ExposedCHQueryError)
