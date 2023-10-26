from ee.clickhouse.materialized_columns.analyze import Query, TeamManager
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.models import Person, PropertyDefinition
from posthog.models.event.util import bulk_create_events
from posthog.test.base import BaseTest, ClickhouseTestMixin


class TestMaterializedColumnsAnalyze(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.DUMMY_QUERIES = [
            (
                f"""
                SELECT JSONExtractString(e.properties, 'event_prop')
                FROM events e
                WHERE team_id = {self.team.pk}
                  AND {trim_quotes_expr("JSONExtractRaw(properties, 'another_prop')")}
                """,
                6723,
            ),
            (
                f"SELECT JSONExtractString(properties, 'person_prop') FROM person WHERE team_id = {self.team.pk}",
                9723,
            ),
            (
                f"""
                SELECT JSONExtractString(person_properties, 'person_prop')
                FROM events
                WHERE team_id = {self.team.pk}
                  AND {trim_quotes_expr("JSONExtractRaw(person_properties, 'another_person_prop')")}
                """,
                6723,
            ),
            (
                f"""
                SELECT JSONExtractString(e.group0_properties, 'group_prop')
                FROM events e
                WHERE team_id = {self.team.pk}
                  AND {trim_quotes_expr("JSONExtractRaw(group2_properties, 'group_prop')")}
                """,
                3100,
            ),
        ]

        # Create property definitions
        PropertyDefinition.objects.create(team=self.team, name="event_prop")
        PropertyDefinition.objects.create(team=self.team, name="another_prop")

        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"person_prop": "something", "$another_prop": "something"},
        )

        bulk_create_events(
            [
                {
                    "event": "some-event",
                    "distinct_id": f"user_id",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "person_properties": {
                        "person_prop": "something",
                        "another_person_prop": "something",
                    },
                    "group0_properties": {"group_prop": "something"},
                    "group2_properties": {"group_prop": "something2"},
                }
            ]
        )

    def test_query_class(self):
        with self.settings(MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME=3000):
            event_query = Query(*self.DUMMY_QUERIES[0])
            person_query = Query(*self.DUMMY_QUERIES[1])
            person_on_events_query = Query(*self.DUMMY_QUERIES[2])
            group_on_events_query = Query(*self.DUMMY_QUERIES[3])

            self.assertTrue(event_query.is_valid)
            self.assertTrue(person_query.is_valid)
            self.assertTrue(person_on_events_query.is_valid)
            self.assertTrue(group_on_events_query.is_valid)

            self.assertEqual(event_query.team_id, str(self.team.pk))
            self.assertEqual(person_query.team_id, str(self.team.pk))
            self.assertEqual(person_on_events_query.team_id, str(self.team.pk))
            self.assertEqual(group_on_events_query.team_id, str(self.team.pk))

            self.assertEqual(
                list(event_query.properties(TeamManager())),
                [
                    ("events", "properties", "event_prop"),
                    ("events", "properties", "another_prop"),
                ],
            )

            self.assertEqual(
                list(person_query.properties(TeamManager())),
                [("person", "properties", "person_prop")],
            )
            self.assertEqual(
                list(person_on_events_query.properties(TeamManager())),
                [
                    ("person", "properties", "person_prop"),
                    ("events", "person_properties", "person_prop"),
                    ("events", "person_properties", "another_person_prop"),
                ],
            )
            self.assertEqual(
                list(group_on_events_query.properties(TeamManager())),
                [
                    ("events", "group0_properties", "group_prop"),
                    ("events", "group2_properties", "group_prop"),
                ],
            )

            self.assertEqual(event_query.cost, 4)
            self.assertEqual(person_query.cost, 7)
            self.assertEqual(person_on_events_query.cost, 4)
            self.assertEqual(group_on_events_query.cost, 1)

    def test_query_class_edge_cases(self):
        invalid_query = Query("SELECT * FROM events WHERE team_id = -1", 100)
        self.assertFalse(invalid_query.is_valid)
        self.assertIsNone(invalid_query.team_id)

        query_with_unknown_property = Query(
            f"SELECT JSONExtractString(properties, '$unknown_prop') FROM events WHERE team_id = {self.team.pk}",
            3400,
        )
        self.assertEqual(list(query_with_unknown_property.properties(TeamManager())), [])

        PropertyDefinition.objects.create(team=self.team, name="prop")

        # match group missing, should probably never happen, since the query is now wrong.
        query_with_invalid_column = Query(
            f"SELECT JSONExtractString(, 'prop') FROM events WHERE team_id = {self.team.pk}",
            3340,
        )
        self.assertEqual(list(query_with_invalid_column.properties(TeamManager())), [])
