from uuid import uuid4

from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.event.util import create_event
from posthog.tasks.test.test_calculate_event_property_usage import calculate_event_property_usage_test_factory


def _create_event(**kwargs) -> None:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)


class CalculateEventPropertyUsage(
    ClickhouseTestMixin, calculate_event_property_usage_test_factory(_create_event),  # type: ignore
):
    pass
