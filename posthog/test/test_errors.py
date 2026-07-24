from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException, UnknownTypeError
from parameterized import parameterized

from posthog.errors import (
    CHQueryErrorUnsupportedVariantType,
    ExposedCHQueryError,
    QueryErrorCategory,
    classify_query_error,
    wrap_clickhouse_query_error,
)


class TestWrapClickhouseQueryError(SimpleTestCase):
    @parameterized.expand(
        [
            ("Unknown type Variant(DateTime64(6, 'America/New_York'), String)",),
            ("Unknown type Variant(Float64, String)",),
        ]
    )
    def test_variant_result_type_becomes_user_safe_error(self, message: str) -> None:
        wrapped = wrap_clickhouse_query_error(UnknownTypeError(message))

        assert isinstance(wrapped, CHQueryErrorUnsupportedVariantType)
        assert isinstance(wrapped, ExposedCHQueryError)
        assert classify_query_error(wrapped) == QueryErrorCategory.USER_ERROR
        assert "toString()" in str(wrapped)

    def test_non_variant_unknown_type_is_left_untouched(self) -> None:
        original = UnknownTypeError("Unknown type SomeBrandNewType")

        wrapped = wrap_clickhouse_query_error(original)

        assert wrapped is original
        assert not isinstance(wrapped, ServerException)
        assert classify_query_error(wrapped) == QueryErrorCategory.ERROR
