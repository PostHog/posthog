import pytest

from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter


@pytest.mark.parametrize(
    "filter,expected_interval",
    [
        (PropertiesTimelineFilter(data={"interval": "hour"}), "hour"),
        (PropertiesTimelineFilter(data={"interval": "day"}), "day"),
        (PropertiesTimelineFilter(data={"interval": "week"}), "week"),
        (PropertiesTimelineFilter(data={"interval": "month"}), "month"),
        # Downcasing
        (PropertiesTimelineFilter(data={"interval": "HoUR"}), "hour"),
        # Blank filter
        (PropertiesTimelineFilter(data={"events": []}), "day"),
        # Legacy support - translate minutes to hours!
        (PropertiesTimelineFilter(data={"interval": "minute"}), "hour"),
    ],
)
def test_filter_interval_success(filter, expected_interval):
    assert filter.interval == expected_interval
    assert filter.interval_to_dict() == {"interval": expected_interval}


@pytest.mark.parametrize(
    "filter,expected_error_message",
    [
        (
            PropertiesTimelineFilter(data={"interval": "foo"}),
            "Interval foo does not belong to SUPPORTED_INTERVAL_TYPES!",
        ),
        (PropertiesTimelineFilter(data={"interval": 123}), "Interval must be a string!"),
    ],
)
def test_filter_interval_errors(filter, expected_error_message):
    with pytest.raises(ValueError, match=expected_error_message):
        filter.interval  # noqa: B018
