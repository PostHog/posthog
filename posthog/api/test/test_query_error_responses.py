from unittest import TestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from rest_framework.exceptions import APIException, ValidationError

from posthog.api.query import QueryViewSet
from posthog.errors import CHQueryErrorS3Error, ExposedCHQueryError, wrap_clickhouse_query_error

# self is unused by the handler, so we can call it unbound rather than standing up the viewset.
_build_response = QueryViewSet._clickhouse_error_response


class TestClickHouseErrorSurfacing(TestCase):
    def test_cannot_parse_bool_is_exposed_to_user(self):
        wrapped = wrap_clickhouse_query_error(
            ServerException(
                "DB::Exception: Cannot parse boolean value here, because it is not one of 'true'/'false'. "
                "Stack trace: 0x... clickhouse-server-abc",
                code=467,
            )
        )
        assert isinstance(wrapped, ExposedCHQueryError)
        message = str(wrapped)
        assert "Cannot parse boolean value" in message
        assert "DB::Exception" not in message
        assert "Stack trace" not in message

    @parameterized.expand(
        [
            ("InvalidRange requested range is not satisfiable", "warehouse_data_resyncing"),
            ("some other S3 failure", "warehouse_read_error"),
        ]
    )
    def test_s3_read_error_is_surfaced_as_user_error(self, raw_message: str, expected_code: str):
        error = wrap_clickhouse_query_error(ServerException(f"DB::Exception: {raw_message}", code=499))
        assert isinstance(error, CHQueryErrorS3Error)

        response = _build_response(None, error)
        assert isinstance(response, ValidationError)
        assert response.get_codes() == [expected_code]

    def test_generic_error_carries_type_and_code_without_leaking_internals(self):
        error = wrap_clickhouse_query_error(
            ServerException(
                "DB::Exception: syntax error at internal-ch-node-42.internal:9000. Stack trace: 0x...",
                code=62,
            )
        )
        response = _build_response(None, error)
        assert isinstance(response, APIException)
        detail = str(response.detail)
        assert "CHQueryErrorSyntaxError" in detail
        assert "62" in detail
        # The generic path must not echo the raw message / infra hostnames.
        assert "internal-ch-node-42" not in detail
        assert "Stack trace" not in detail
