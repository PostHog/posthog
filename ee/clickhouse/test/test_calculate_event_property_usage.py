from ee.clickhouse.util import ClickhouseTestMixin
from posthog.tasks.test.test_calculate_event_property_usage import calculate_event_property_usage_test_factory
from posthog.test.base import _create_event


class CalculateEventPropertyUsage(
    ClickhouseTestMixin, calculate_event_property_usage_test_factory(_create_event),  # type: ignore
):
    pass
