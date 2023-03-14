import pytest

from posthog.models import Filter, Team


@pytest.mark.parametrize(
    "data,expected_interval",
    [
        ({"interval": "hour"}, "hour"),
        ({"interval": "day"}, "day"),
        ({"interval": "week"}, "week"),
        ({"interval": "month"}, "month"),
        # Downcasing
        ({"interval": "HoUR"}, "hour"),
        # Blank filter
        ({"events": []}, "day"),
        # Legacy support - translate minutes to hours!
        ({"interval": "minute"}, "hour"),
    ],
)
def test_filter_interval_success(data, expected_interval):
    filter = Filter(data=data, team=Team())
    assert filter.interval == expected_interval
    assert filter.interval_to_dict() == {"interval": expected_interval}


@pytest.mark.parametrize(
    "data,expected_error_message",
    [
        ({"interval": "foo"}, "Interval foo does not belong to SUPPORTED_INTERVAL_TYPES!"),
        ({"interval": 123}, "Interval must be a string!"),
    ],
)
def test_filter_interval_errors(data, expected_error_message):
    with pytest.raises(ValueError, match=expected_error_message):
        Filter(data=data, team=Team()).interval
