import pytest

from posthog.models import Filter


@pytest.mark.parametrize(
    "filter,expected_interval",
    [
        (Filter(data={"interval": "hour"}), "hour"),
        (Filter(data={"interval": "day"}), "day"),
        (Filter(data={"interval": "week"}), "week"),
        (Filter(data={"interval": "month"}), "month"),
        # Downcasing
        (Filter(data={"interval": "HoUR"}), "hour"),
        # Blank filter
        (Filter(data={"events": []}), "day"),
        # Legacy support - translate minutes to hours!
        (Filter(data={"interval": "minute"}), "hour"),
    ],
)
def test_filter_interval_success(filter, expected_interval):
    assert filter.interval == expected_interval
    assert filter.interval_to_dict() == {"interval": expected_interval}


@pytest.mark.parametrize(
    "filter,expected_error_message",
    [
        (
            Filter(data={"interval": "foo"}),
            "Interval foo does not belong to SUPPORTED_INTERVAL_TYPES!",
        ),
        (Filter(data={"interval": 123}), "Interval must be a string!"),
    ],
)
def test_filter_interval_errors(filter, expected_error_message):
    with pytest.raises(ValueError, match=expected_error_message):
        filter.interval  # noqa: B018
