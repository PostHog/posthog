import pytest

from posthog.temporal.data_imports.sources.redshift.source import RedshiftSource


class TestRedshiftSourceNonRetryableErrors:
    @pytest.fixture
    def source(self):
        return RedshiftSource()

    def test_connection_timeout_expired_is_retryable(self, source):
        non_retryable = source.get_non_retryable_errors()
        assert "connection timeout expired" not in non_retryable

    @pytest.mark.parametrize(
        "error_msg",
        [
            "ConnectionTimeout: connection timeout expired",
            'connection failed: connection to server at "10.0.0.1", port 5439 failed: connection timeout expired',
        ],
    )
    def test_transient_connection_timeouts_are_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient error should be retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            'could not translate host name "bad-hostname.example.com" to address: Name or service not known',
            'FATAL:  password authentication failed for user "myuser"',
            "SSL connection has been closed unexpectedly",
            "Network is unreachable",
            "No route to host",
            "Connection refused",
        ],
    )
    def test_permanent_connection_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Permanent error should be non-retryable: {error_msg}"
