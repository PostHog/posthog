from ee.clickhouse.models.action import populate_action_event_table
from ee.clickhouse.models.cohort import populate_cohort_person_table
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person
from ee.clickhouse.queries.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.queries.test.test_trends import trend_test_factory


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    populate_action_event_table(action)
    return action


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups)
    populate_cohort_person_table(cohort)
    return cohort


class TestClickhouseTrends(ClickhouseTestMixin, trend_test_factory(ClickhouseTrends, create_event, create_person, _create_action, _create_cohort)):  # type: ignore
    pass
