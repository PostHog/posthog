from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_element import test_element_factory
from posthog.models import Event


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    return Event(pk=create_event(**kwargs))


class TestElement(
    ClickhouseTestMixin, test_element_factory(_create_event)  # type: ignore
):
    pass
