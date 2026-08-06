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
            # Ambiguous-identifier query errors are the user's malformed HogQL, not a server fault,
            # so they must wrap as ExposedCHQueryError and stay out of error tracking.
            (207, "AMBIGUOUS_IDENTIFIER"),
            (352, "AMBIGUOUS_COLUMN_NAME"),
        ]
    )
    def test_ambiguous_identifier_codes_wrap_as_exposed_error(self, code: int, name: str) -> None:
        err = ServerException(f"DB::Exception: {name}", code=code)

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, ExposedCHQueryError)
        assert look_up_clickhouse_error_code_meta(err).get_category() == QueryErrorCategory.USER_ERROR

    def test_unmapped_internal_code_stays_internal(self) -> None:
        # NETWORK_ERROR (210) is a genuine server-side fault and must not be exposed.
        err = ServerException("DB::Exception: NETWORK_ERROR", code=210)

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, InternalCHQueryError)
        assert not isinstance(wrapped, ExposedCHQueryError)
