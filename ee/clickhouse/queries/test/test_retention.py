from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person, create_person_with_distinct_id
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.person import Person
from posthog.queries.test.test_retention import retention_test_factory


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    team_id = kwargs.pop("team_id")
    distinct_ids = kwargs.pop("distinct_ids")

    create_person(team_id=team_id, id=person.pk)
    create_person_with_distinct_id(person_id=person.pk, team_id=team_id, distinct_ids=distinct_ids)


class TestClickhouseRetention(ClickhouseTestMixin, retention_test_factory(ClickhouseRetention, create_event=create_event, create_person=_create_person)):  # type: ignore

    # override original test
    def test_retention_with_properties(self):
        pass

    # override original test
    def test_retention_action_start_point(self):
        pass
