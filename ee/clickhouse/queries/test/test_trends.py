from ee.clickhouse.models.action import populate_action_event_table
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person, create_person_with_distinct_id
from ee.clickhouse.queries.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.person import Person
from posthog.queries.test.test_trends import trend_test_factory


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    team_id = kwargs.pop("team_id")
    distinct_ids = kwargs.pop("distinct_ids")

    create_person(team_id=team_id, id=person.pk)
    create_person_with_distinct_id(person_id=person.pk, team_id=team_id, distinct_ids=distinct_ids)


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    populate_action_event_table(action)
    return action


class TestClickhouseTrends(ClickhouseTestMixin, trend_test_factory(ClickhouseTrends, create_event, _create_person, _create_action)):  # type: ignore
    pass
