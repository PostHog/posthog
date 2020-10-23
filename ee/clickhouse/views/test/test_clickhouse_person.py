from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_person import test_person_factory
from posthog.models import Action, ActionStep, Event, Person


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    return Event(pk=create_event(**kwargs))


def _get_events():
    return sync_execute("select * from events")


def _get_people():
    return [Person(p) for p in sync_execute("select * from person")]


def _create_person(**kwargs):
    return Person.objects.create(**kwargs)


class ClickhouseTestPersonApi(
    ClickhouseTestMixin, test_person_factory(_create_event, _create_person, _get_events, Person.objects.all)  # type: ignore
):
    pass
