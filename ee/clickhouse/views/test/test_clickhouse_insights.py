from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_insight import insight_test_factory
from posthog.models.person import Person


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class ClickhouseTestInsights(
    ClickhouseTestMixin, insight_test_factory(_create_event, _create_person)  # type: ignore
):
    pass
