from posthog.test.base import ClickhouseTestMixin, BaseTest, _create_event
from posthog.client import sync_execute
from posthog.dag.execute import DAG


class TestPerson(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        sync_execute("drop database if exists posthog_dag;")
        sync_execute("create database posthog_dag;")
        DAG().set_up()

    def test_calculate_person_distinct_id(self):
        # A simple anonymous id -> distinct_id merge
        _create_event(event="$pageview", distinct_id="anonymous_id4", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id3",
            properties={"$anon_distinct_id": "anonymous_id4"},
            team=self.team,
        )

        # Singular anonymous distinct id, not merged
        _create_event(event="$pageview", distinct_id="anonymous_id5", team=self.team)

        DAG().person_distinct_id_table()
        persons = sync_execute(
            "select groupArray(distinct_id) from posthog_dag.person_distinct_id where team_id = %(team_id)s group by person_id order by groupArray(distinct_id)",
            {"team_id": self.team.pk},
        )
        self.assertEqual(persons[0][0], ["anonymous_id4", "distinct_id3"])
        self.assertEqual(persons[1][0], ["anonymous_id5"])

    def test_create_alias_simple(self):
        _create_event(event="$pageview", distinct_id="distinct_id1", team=self.team)
        _create_event(event="$pageview", distinct_id="distinct_id2", team=self.team)

        _create_event(
            event="$create_alias", distinct_id="distinct_id1", properties={"alias": "distinct_id2"}, team=self.team
        )

        DAG().person_distinct_id_table()
        persons = sync_execute(
            "select groupArray(distinct_id) from posthog_dag.person_distinct_id where team_id = %(team_id)s group by person_id order by groupArray(distinct_id)",
            {"team_id": self.team.pk},
        )
        self.assertEqual(persons[0][0], ["distinct_id1", "distinct_id2"])

    def test_create_alias_complex(self):
        _create_event(event="$pageview", distinct_id="anonymous_id1", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id1"},
            team=self.team,
        )

        _create_event(event="$pageview", distinct_id="anonymous_id2", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id2"},
            team=self.team,
        )

        _create_event(event="$pageview", distinct_id="distinct_id2", team=self.team)

        _create_event(
            event="$create_alias", distinct_id="distinct_id1", properties={"alias": "distinct_id2"}, team=self.team
        )

        DAG().person_distinct_id_table()
        persons = sync_execute(
            """
            select groupArray(distinct_id) from (
                select
                    distinct_id,
                    argMax(person_id, _timestamp) as person_id
                from
                    posthog_dag.person_distinct_id
                where team_id = %(team_id)s
                group by distinct_id
            )
            group by person_id
            order by groupArray(distinct_id)
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(persons[0][0], ["distinct_id2", "anonymous_id2", "distinct_id1", "anonymous_id1"])

    def test_create_alias_fail(self):
        _create_event(event="$pageview", distinct_id="anonymous_id1", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id1"},
            team=self.team,
        )

        _create_event(event="$pageview", distinct_id="anonymous_id2", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id2"},
            team=self.team,
        )

        _create_event(event="$pageview", distinct_id="anonymous_id3", team=self.team)
        # Because distinct_id2 has already been identified, we do not allow a merge
        _create_event(
            event="$identify",
            distinct_id="distinct_id2",
            properties={"$anon_distinct_id": "anonymous_id3"},
            team=self.team,
        )

        _create_event(
            event="$create_alias", distinct_id="distinct_id2", properties={"alias": "distinct_id1"}, team=self.team
        )

        DAG().person_distinct_id_table()
        persons = sync_execute(
            "select groupArray(distinct_id) from posthog_dag.person_distinct_id where team_id = %(team_id)s group by person_id order by groupArray(distinct_id)",
            {"team_id": self.team.pk},
        )
        self.assertEqual(persons[0][0], ["anonymous_id1", "anonymous_id2", "distinct_id1"])
        self.assertEqual(persons[1][0], ["anonymous_id3", "distinct_id2"])

    def test_merge_dangerously(self):
        # Same setup as tests above
        _create_event(event="$pageview", distinct_id="anonymous_id1", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id1"},
            team=self.team,
        )

        _create_event(event="$pageview", distinct_id="anonymous_id2", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id2"},
            team=self.team,
        )

        _create_event(event="$pageview", distinct_id="anonymous_id3", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id2",
            properties={"$anon_distinct_id": "anonymous_id3"},
            team=self.team,
        )

        # but we merge dangerously
        _create_event(
            event="$merge_dangerously", distinct_id="distinct_id2", properties={"alias": "distinct_id1"}, team=self.team
        )

        DAG().person_distinct_id_table()
        persons = sync_execute(
            "select groupArray(distinct_id) from posthog_dag.person_distinct_id where team_id = %(team_id)s group by person_id order by groupArray(distinct_id)",
            {"team_id": self.team.pk},
        )
        self.assertEqual(
            persons[0][0], ["anonymous_id1", "anonymous_id2", "anonymous_id3", "distinct_id1", "distinct_id2"]
        )

    def test_anonymous_id_merge_with_partial(self):
        # A simple anonymous id -> distinct_id merge
        _create_event(event="$pageview", distinct_id="anonymous_id1", team=self.team)
        _create_event(event="$pageview", distinct_id="distinct_id1", team=self.team)

        run_time = sync_execute("select max(_timestamp) from events")[0][0]
        DAG().person_distinct_id_table(until_timestamp=run_time)
        prev_persons = self._get_persons()
        self.assertEqual(prev_persons[0][0], ["anonymous_id1"])
        self.assertEqual(prev_persons[1][0], ["distinct_id1"])

        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id1"},
            team=self.team,
        )

        DAG().person_distinct_id_table(from_timestamp=run_time)

        persons = self._get_persons()
        self.assertEqual(persons[0][0], ["distinct_id1", "anonymous_id1"])
        self.assertEqual(prev_persons[1][1], persons[0][1])  # ensure person id is consistent
        self.assertEqual(len(persons), 1)

    def test_merge_dangerously_with_partial(self):
        _create_event(event="$pageview", distinct_id="anonymous_id1", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id1"},
            team=self.team,
        )

        _create_event(event="$pageview", distinct_id="anonymous_id2", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id1",
            properties={"$anon_distinct_id": "anonymous_id2"},
            team=self.team,
        )

        _create_event(event="$pageview", distinct_id="anonymous_id3", team=self.team)
        _create_event(
            event="$identify",
            distinct_id="distinct_id2",
            properties={"$anon_distinct_id": "anonymous_id3"},
            team=self.team,
        )

        run_time = sync_execute("select max(_timestamp) from events")[0][0]
        DAG().person_distinct_id_table(until_timestamp=run_time)
        prev_persons = self._get_persons()
        self.assertEqual(prev_persons[0][0], ["anonymous_id2", "distinct_id1", "anonymous_id1"])
        self.assertEqual(prev_persons[1][0], ["distinct_id2", "anonymous_id3"])

        _create_event(
            event="$merge_dangerously", distinct_id="distinct_id2", properties={"alias": "distinct_id1"}, team=self.team
        )

        DAG().person_distinct_id_table(from_timestamp=run_time)

        persons = self._get_persons()
        self.assertEqual(
            persons[0][0], ["distinct_id2", "anonymous_id2", "anonymous_id3", "distinct_id1", "anonymous_id1"]
        )
        self.assertEqual(prev_persons[1][1], persons[0][1])  # ensure person id is consistent
        self.assertEqual(len(persons), 1)

    def _get_persons(self):
        return sync_execute(
            """
            select groupArray(distinct_id), person_id from (
                select
                    distinct_id,
                    argMax(person_id, _timestamp) as person_id
                from
                    posthog_dag.person_distinct_id
                where team_id = %(team_id)s
                group by distinct_id
            )
            group by person_id
            order by groupArray(distinct_id)
            """,
            {"team_id": self.team.pk},
        )
