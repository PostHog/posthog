import pytest

from posthog.temporal.data_imports.sources.snowflake.source import SnowflakeSource


class TestSnowflakeSourceNonRetryableErrors:
    @pytest.fixture
    def source(self) -> SnowflakeSource:
        return SnowflakeSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            "snowflake.connector.errors.ProgrammingError: 002334 (42601): SQL compilation error: View columns mismatch with view definition for view 'GOODS' at line 1, position 25, please re-create the view",
            "002334 (42601): SQL compilation error: View columns mismatch with view definition for view 'ORDERS'",
            "SQL compilation error: please re-create the view",
            "ProgrammingError: This account has been marked for decommission",
            "Your free trial has ended",
            "MFA authentication is required for this user",
            "invalid credentials",
            "authentication failed",
        ],
    )
    def test_stale_view_and_known_errors_are_non_retryable(self, source: SnowflakeSource, error_msg: str) -> None:
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Permanent error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Connection reset by peer",
            "Operation timed out",
            "Internal Server Error",
        ],
    )
    def test_transient_errors_are_retryable(self, source: SnowflakeSource, error_msg: str) -> None:
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient error should be retryable: {error_msg}"

    def test_stale_view_message_is_actionable(self, source: SnowflakeSource) -> None:
        non_retryable = source.get_non_retryable_errors()
        message = non_retryable["View columns mismatch with view definition"]
        assert message is not None
        assert "recreate" in message.lower() or "re-create" in message.lower()
