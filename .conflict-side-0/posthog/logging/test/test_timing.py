from unittest.mock import Mock, call, patch

from posthog.logging.timing import timed


@patch("posthog.logging.timing.statsd.timer")
def test_wrap_with_timing_calls_statsd(mock_timer) -> None:
    timer_instance = Mock()
    mock_timer.return_value = timer_instance

    @timed(name="test")
    def test_func():
        pass

    test_func()

    mock_timer.assert_called_with("test")
    timer_instance.assert_has_calls(calls=[call.start(), call.start().stop()])
