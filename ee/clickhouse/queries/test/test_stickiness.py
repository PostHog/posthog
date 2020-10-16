from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.person import Person
from posthog.queries.test.test_stickiness import stickiness_test_factory


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    event_name = kwargs.pop("event_name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=event_name)
    return action


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseStickiness(ClickhouseTestMixin, stickiness_test_factory(ClickhouseStickiness, _create_event, Person.objects.create, _create_action)):  # type: ignore
    pass
