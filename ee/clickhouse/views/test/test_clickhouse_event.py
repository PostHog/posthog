from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_event import test_event_api_factory
from posthog.models import Action, ActionStep, Event, Person


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    return Event(pk=create_event(**kwargs))


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


class ClickhouseTestEventApi(
    ClickhouseTestMixin, test_event_api_factory(_create_event, _create_person, _create_action)  # type: ignore
):
    def test_live_action_events(self):
        pass
