import pytest

from posthog.temporal.data_imports.sources.mssql.source import MSSQLSource


class TestMSSQLSourceNonRetryableErrors:
    @pytest.fixture
    def source(self):
        return MSSQLSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Cannot build decimal array from values",
            "ValueError: Cannot build decimal array from values",
        ],
    )
    def test_unrepresentable_decimal_values_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Unrepresentable decimal error should be non-retryable: {error_msg}"
