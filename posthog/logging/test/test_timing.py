from unittest.mock import patch

from posthog.logging.timing import timed


@patch("posthog.logging.timing.TIMED_DECORATOR_HISTOGRAM")
def test_wrap_with_timing_records_histogram(mock_histogram) -> None:
    @timed(name="test")
    def test_func():
        pass

    test_func()

    mock_histogram.labels.assert_called_with(name="test")
    mock_histogram.labels.return_value.time.assert_called_once()
