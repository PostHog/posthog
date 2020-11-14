from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.event import Event
from posthog.tasks.test.test_calculate_event_property_usage import test_calculate_event_property_usage


def _create_event(**kwargs) -> Event:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return Event(pk=str(pk))


class CalculateEventPropertyUsage(
    ClickhouseTestMixin, test_calculate_event_property_usage(_create_event),  # type: ignore
):
    pass
