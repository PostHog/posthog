from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.errors import ExposedCHQueryError, InternalCHQueryError, wrap_clickhouse_query_error


class TestWarehouseReadErrorsAreExposed:
    # Errors ClickHouse raises while reading a synced data-warehouse table (Delta/Parquet on S3).
    # These must surface to the user instead of being masked as the generic
    # "ClickHouse error while executing query." string, otherwise a table that synced but can't be
    # read back is undiagnosable.
    @parameterized.expand(
        [
            (636, "cannot_extract_table_structure"),
            (723, "parquet_exception"),
            (742, "delta_kernel_error"),
        ]
    )
    def test_lake_read_error_wraps_to_exposed_error_with_sanitized_message(self, code: int, code_name: str) -> None:
        server_error = ServerException(
            f"DB::Exception: Cannot read column 'amount': type mismatch, expected Decimal but got String. "
            f"(code {code}) Stack trace: 0x deep in the cluster",
            code=code,
        )
        wrapped = wrap_clickhouse_query_error(server_error)

        assert isinstance(wrapped, ExposedCHQueryError)
        assert getattr(wrapped, "code_name", None) == code_name

        message = str(wrapped)
        assert "DB::Exception" not in message
        assert "Stack trace" not in message
        assert "type mismatch, expected Decimal but got String" in message

    def test_unknown_internal_error_stays_hidden(self) -> None:
        # A truly-internal code keeps masking its raw message, so the split still holds.
        server_error = ServerException("DB::Exception: some internal cluster detail. Stack trace: ...", code=999)
        wrapped = wrap_clickhouse_query_error(server_error)
        assert isinstance(wrapped, InternalCHQueryError)
        assert not isinstance(wrapped, ExposedCHQueryError)
