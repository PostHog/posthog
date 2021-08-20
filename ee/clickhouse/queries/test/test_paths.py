from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.materialized_columns.columns import materialize
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.queries.paths.paths import ClickhousePathsNew
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import PAGEVIEW_EVENT, SCREEN_EVENT
from posthog.models.filters.path_filter import PathFilter
from posthog.models.person import Person
from posthog.queries.test.test_paths import paths_test_factory


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhousePathsOld(ClickhouseTestMixin, paths_test_factory(ClickhousePaths, _create_event, Person.objects.create)):  # type: ignore
    # remove when migrated to new Paths query
    def test_denormalized_properties(self):
        materialize("events", "$current_url")
        materialize("events", "$screen_name")

        query, _ = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": PAGEVIEW_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        query, _ = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": SCREEN_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        self.test_current_url_paths_and_logic()


class TestClickhousePaths(ClickhouseTestMixin, paths_test_factory(ClickhousePathsNew, _create_event, Person.objects.create)):  # type: ignore
    def test_denormalized_properties(self):
        materialize("events", "$current_url")
        materialize("events", "$screen_name")

        query, _ = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": PAGEVIEW_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        query, _ = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": SCREEN_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        self.test_current_url_paths_and_logic()

    def test_paths_start(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
        )

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person_2"])
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/pricing"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_2", event="$pageview", team=self.team,
        )

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person_3"])
        _create_event(
            properties={"$current_url": "/pricing"}, distinct_id="person_3", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_3", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_3", event="$pageview", team=self.team,
        )

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person_4"])
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_4", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/pricing"}, distinct_id="person_4", event="$pageview", team=self.team,
        )

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person_5a", "person_5b"])
        _create_event(
            properties={"$current_url": "/pricing"}, distinct_id="person_5a", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_5b", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/pricing"}, distinct_id="person_5a", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/help"}, distinct_id="person_5b", event="$pageview", team=self.team,
        )

        response = self.client.get("/api/insight/path/?type=%24pageview&start=%2Fpricing").json()

        filter = PathFilter(data={"path_type": "$pageview", "start_point": "/pricing"})
        response = ClickhousePathsNew(team=self.team, filter=filter).run(team=self.team, filter=filter,)

        self.assertEqual(len(response), 5)

        self.assertTrue(response[0].items() == {"source": "1_/pricing", "target": "2_/", "value": 1}.items())
        self.assertTrue(response[1].items() == {"source": "1_/pricing", "target": "2_/about", "value": 1}.items())
        self.assertTrue(response[2].items() == {"source": "2_/", "target": "3_/about", "value": 1}.items())
        self.assertTrue(response[3].items() == {"source": "2_/about", "target": "3_/pricing", "value": 1}.items())
        self.assertTrue(response[4].items() == {"source": "3_/pricing", "target": "4_/help", "value": 1}.items())

        filter = PathFilter(data={"path_type": "$pageview", "start_point": "/"})
        response = ClickhousePathsNew(team=self.team, filter=filter).run(team=self.team, filter=filter,)

        self.assertEqual(len(response), 3)
        self.assertTrue(response[0].items() == {"source": "1_/", "target": "2_/pricing", "value": 2}.items())
        self.assertTrue(response[1].items() == {"source": "1_/", "target": "2_/about", "value": 1}.items())
        self.assertTrue(response[2].items() == {"source": "2_/pricing", "target": "3_/about", "value": 1}.items())
