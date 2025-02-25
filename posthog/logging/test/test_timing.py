import pytest
from posthog.logging.timing import (
    timed,
    timed_log,
)
from time import (
    time,
)
from unittest.mock import (
    Mock,
    call,
    patch,
)


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


@patch("builtins.print")
@patch("posthog.logging.timing.time", side_effect=[1000.0, 1000.1])
def test_timed_log_prints_correct_message(mock_time, mock_print):
    """
    Test that the timed_log decorator correctly prints the expected timing information,
    including using a custom name and properly logging the function arguments.
    """

    @timed_log(name="custom-test-func")
    def dummy(a, b, flag=False):
        return a + b if flag is False else a * b

    result = dummy(3, 4, flag=False)
    assert result == 7
    expected_message = "Timed function: custom-test-func took 100.0ms with args"
    expected_args = {"args": (3, 4), "kwargs": {"flag": False}}
    mock_print.assert_called_once_with(expected_message, expected_args)


@patch("posthog.logging.timing.statsd.timer")
def test_timed_decorator_exception_stops_timer(mock_timer):
    """
    Test that the timed decorator calls timer.stop() even when the decorated function raises an exception.
    This ensures that resources are cleaned up properly even in error scenarios.
    """
    timer_instance = Mock()
    timer_instance.start.return_value = timer_instance
    mock_timer.return_value = timer_instance

    @timed("exception-timing")
    def failing_function():
        raise ValueError("Intentional error for testing")

    with pytest.raises(ValueError, match="Intentional error for testing"):
        failing_function()
    timer_instance.stop.assert_called_once()


@patch("builtins.print")
@patch("posthog.logging.timing.time", side_effect=[2000.0, 2000.05])
def test_timed_log_uses_default_function_name(mock_time, mock_print):
    """
    Test that the timed_log decorator uses the function's __name__ as the default
    name when no custom name is provided and prints the expected timing information.
    The test patches time to simulate a 50ms duration.
    """

    @timed_log()
    def sample_function(a, b):
        return a - b

    result = sample_function(20, 5)
    assert result == 15
    expected_message = "Timed function: sample_function took 50.0ms with args"
    expected_args = {"args": (20, 5), "kwargs": {}}
    mock_print.assert_called_once_with(expected_message, expected_args)


@patch("builtins.print")
@patch("posthog.logging.timing.time", side_effect=[3000.0, 3000.2])
def test_timed_log_prints_on_exception(mock_time, mock_print):
    """
    Test that the timed_log decorator prints the timing information even when the decorated function raises an exception.
    The test patches time to simulate a 200ms duration.
    """

    @timed_log()
    def dummy_fail(a, b, key=None):
        raise ValueError("Intentional failure")

    with pytest.raises(ValueError, match="Intentional failure"):
        dummy_fail(1, 2, key="value")
    expected_message = "Timed function: dummy_fail took 200.0ms with args"
    expected_args = {"args": (1, 2), "kwargs": {"key": "value"}}
    mock_print.assert_called_once_with(expected_message, expected_args)
