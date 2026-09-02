from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.errors import (
    ExposedCHQueryError,
    InternalCHQueryError,
    QueryErrorCategory,
    look_up_clickhouse_error_code_meta,
    wrap_clickhouse_query_error,
)


class TestWrapClickhouseQueryError:
    @parameterized.expand(
        [
            # These reveal only the user's own query or schema, not stored data values, so they wrap
            # as ExposedCHQueryError and expose the real ClickHouse message. Reverting any to
            # non-user_safe reintroduces the generic "ClickHouse error while executing query." message.
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
            # These are exposed but their raw CH message embeds a per-row data value, so they carry a
            # fixed user_safe string. The assertion guards against a revert to user_safe=True, which
            # would pass the raw ClickHouse text (and the source value) straight through.
            (69, "ARGUMENT_OUT_OF_BOUND", "An argument is out of bounds."),
            (
                70,
                "CANNOT_CONVERT_TYPE",
                "Cannot convert one type to another in the query. Check the types in your comparisons and IN clauses.",
            ),
            (407, "DECIMAL_OVERFLOW", "Decimal overflow while executing query."),
        ]
    )
    def test_fixed_message_codes_hide_raw_clickhouse_text(self, code: int, name: str, message: str) -> None:
        err = ServerException(f"DB::Exception: {name} leaked_value=42", code=code)

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, ExposedCHQueryError)
        assert str(wrapped) == message

    @parameterized.expand(
        [
            # NETWORK_ERROR (210) is a genuine server-side fault and must not be exposed.
            (210, "NETWORK_ERROR"),
            # SYNTAX_ERROR (62) stays internal: HogQL validates syntax first, so a raw CH syntax error
            # signals a PostHog SQL-generation bug that belongs in error tracking.
            (62, "SYNTAX_ERROR"),
            # These parse/convert codes embed the failing data value in the CH message, so they stay
            # internal to avoid leaking source values on public shared insights.
            (6, "CANNOT_PARSE_TEXT"),
            (72, "CANNOT_PARSE_NUMBER"),
            (675, "CANNOT_PARSE_IPV4"),
            (676, "CANNOT_PARSE_IPV6"),
            (691, "UNKNOWN_ELEMENT_OF_ENUM"),
        ]
    )
    def test_codes_stay_internal(self, code: int, name: str) -> None:
        err = ServerException(f"DB::Exception: {name}", code=code)

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, InternalCHQueryError)
        assert not isinstance(wrapped, ExposedCHQueryError)
