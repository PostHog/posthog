from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from ee.clickhouse.queries.related_actors_query import RelatedActorsQuery

PATH = "ee.clickhouse.queries.related_actors_query"


@freeze_time("2025-03-01T12:00:00Z")
class TestRelatedActorsQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.person = _create_person(distinct_ids=["user1"], team=self.team)
        self.another_person = _create_person(distinct_ids=["user2"], team=self.team)
        self.unrelated_person = _create_person(distinct_ids=["user3"], team=self.team)
        self.old_related_person = _create_person(distinct_ids=["user4"], team=self.team)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp=datetime(2025, 2, 15, 12, 0, 0),
            properties={"$group_0": "org:1"},
            person_id=self.person,
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp=datetime(2025, 2, 15, 12, 0, 0),
            properties={"$group_0": "org:1"},
            person_id=self.person,
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp=datetime(2025, 2, 15, 12, 0, 0),
            properties={"$group_0": "another-org"},
            person_id=self.unrelated_person,
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user4",
            timestamp=datetime(2024, 2, 15, 12, 0, 0),
            properties={"$group_0": "org:1"},
            person_id=self.unrelated_person,
        )
        flush_persons_and_events()

    def _query(self) -> list:
        return RelatedActorsQuery(team=self.team, group_type_index=0, id="org:1").run()

    @snapshot_clickhouse_queries
    @patch(f"{PATH}.posthoganalytics.feature_enabled", return_value=False)
    def test_query_related_people_control(self, _):
        results = self._query()

        assert len(results) == 2
        person = results[0]
        assert person["type"] == "person"
        assert person["id"] == str(self.person.uuid)

    @snapshot_clickhouse_queries
    @patch(f"{PATH}.posthoganalytics.feature_enabled", return_value=True)
    def test_query_related_people_optimized(self, _):
        results = self._query()

        assert len(results) == 2
        person = results[0]
        assert person["type"] == "person"
        assert person["id"] == str(self.person.uuid)
