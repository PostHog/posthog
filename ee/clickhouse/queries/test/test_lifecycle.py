from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.person import Person
from posthog.queries.test.test_lifecycle import lifecycle_test_factory


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseLifecycle(ClickhouseTestMixin, lifecycle_test_factory(ClickhouseTrends, _create_event, Person.objects.create, _create_action)):  # type: ignore
    pass
