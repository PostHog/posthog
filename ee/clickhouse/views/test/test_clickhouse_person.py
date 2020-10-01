from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import populate_action_event_table
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person, get_persons
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_person import test_person_api_factory
from posthog.models import Action, ActionStep, Event, Person


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    return Event(pk=create_event(**kwargs))


def _event_count():
    return sync_execute("select count(1) from event")


class ClickhouseTestPersonApi(
    ClickhouseTestMixin, test_person_api_factory(_create_event, create_person, _event_count, get_persons)  # type: ignore
):
    pass
