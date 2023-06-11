from posthog.test.base import ClickhouseTestMixin, BaseTest, _create_event
from posthog.client import sync_execute
from posthog.dag.execute import DAG
from django.utils.timezone import now
import json


class TestPerson(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        sync_execute("drop database if exists posthog_dag;")
        sync_execute("create database posthog_dag;")
        DAG().set_up()

    def test_calculate_person_properties_with_merge(self):
        _create_event(
            event="$pageview", distinct_id="distinct_id1", properties={"$set": {"prop1": "val1"}}, team=self.team
        )
        _create_event(
            event="$pageview",
            distinct_id="anonymous_id1",
            properties={"$set": {"prop1": "val2", "prop2": "val1"}},
            team=self.team,
        )
        # Prioritise properties from the identified user, even if it's later
        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id1"},
            team=self.team,
        )

        DAG().person_distinct_id_table()
        DAG().person_table()
        person = sync_execute(
            "select properties from posthog_dag.person where team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        self.assertDictEqual(json.loads(person[0][0]), {"prop1": "val2", "prop2": "val1"})

    def test_person_no_properties(self):
        _create_event(event="$pageview", distinct_id="anonymous_id1", properties={}, team=self.team)
        DAG().person_distinct_id_table()
        DAG().person_table()
        person = sync_execute(
            "select count(1) from posthog_dag.person where team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        self.assertEqual(person[0][0], 1)

    def test_partial_properties(self):
        _create_event(
            event="$pageview", distinct_id="distinct_id1", properties={"$set": {"prop1": "val1"}}, team=self.team
        )
        run_time = now()
        DAG().person_distinct_id_table()
        DAG().person_table(until_timestamp=run_time())

        person = sync_execute(
            "select count(1) from posthog_dag.person where team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        self.assertEqual(person[0][0], 1)
        _create_event(
            event="$pageview", distinct_id="distinct_id1", properties={"$set": {"prop1": "val2"}}, team=self.team
        )

        DAG().person_distinct_id_table()
        DAG().person_table(from_timestamp=run_time())

        person = sync_execute(
            "select version, properties from posthog_dag.person where team_id = %(team_id)s order by version desc",
            {"team_id": self.team.pk},
        )
        self.assertEqual(person[0], [1, '{"prop1": "val2"}'])

    # Cases to test
    # (set1, set2) -> set2
    # (set_once1, set_once2) -> set_once1
    # (set_once1, set1) -> set1
    # (set1, set_once1) -> set1
    # (set_once1, set1, set_once2) -> set1
    def test_set1_set2(self):
        _test_set_unset(
            team=self.team,
            events=[
                {"$set": {"prop1": "val1"}},
                {"$set": {"prop1": "val2"}},
            ],
            result={"prop1": "val2"},
        )

    def test_set_once1__set_once2(self):
        _test_set_unset(
            team=self.team,
            events=[
                {"$set_once": {"prop1": "val1"}},
                {"$set_once": {"prop1": "val2"}},
            ],
            result={"prop1": "val1"},
        )

    def test_set_once1__set(self):
        _test_set_unset(
            team=self.team,
            events=[
                {"$set_once": {"prop1": "val1"}},
                {"$set": {"prop1": "val2"}},
            ],
            result={"prop1": "val2"},
        )

    def test_set__set_once(self):
        _test_set_unset(
            team=self.team,
            events=[
                {"$set": {"prop1": "val1"}},
                {"$set_once": {"prop1": "val2"}},
            ],
            result={"prop1": "val1"},
        )

    def test_set_once__set__set_once(self):
        _test_set_unset(
            team=self.team,
            events=[
                {"$set_once": {"prop1": "val1"}},
                {"$set": {"prop1": "val2"}},
                {"$set_once": {"prop1": "val3"}},
            ],
            result={"prop1": "val2"},
        )


def _test_set_unset(events, result, team):

    for event in events:
        _create_event(properties=event, event="$pageview", distinct_id="distinct_id1", team=team)

    DAG().person_distinct_id_table()
    DAG().person_table()
    person = sync_execute("select properties from posthog_dag.person where team_id = %(team_id)s", {"team_id": team.pk})
    assert json.loads(person[0][0]) == result
