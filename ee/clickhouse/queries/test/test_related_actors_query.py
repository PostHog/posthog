from datetime import datetime
from uuid import uuid4

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

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

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
        self._create_group_event("user1", "org:1", datetime(2025, 2, 15, 12, 0, 0))
        self._create_group_event("user2", "org:1", datetime(2025, 2, 15, 12, 0, 0))
        self._create_group_event("user3", "another-org", datetime(2025, 2, 15, 12, 0, 0))
        self._create_group_event("user4", "org:1", datetime(2024, 2, 15, 12, 0, 0))
        flush_persons_and_events()

    def _create_group_event(self, distinct_id: str, group_key: str, timestamp: datetime) -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={"$group_0": group_key},
        )

    def _insert_pdi2_row(self, distinct_id: str, person_id: str, version: int, is_deleted: int = 0) -> None:
        sync_execute(
            "INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version) VALUES",
            [(self.team.pk, distinct_id, person_id, is_deleted, version)],
        )

    def _query(self) -> list:
        return RelatedActorsQuery(team=self.team, group_type_index=0, id="org:1").run()

    @staticmethod
    def _get_person_ids(results: list) -> set[str]:
        return {r["id"] for r in results if r["type"] == "person"}

    @snapshot_clickhouse_queries
    @patch(f"{PATH}.posthoganalytics.feature_enabled", return_value=False)
    def test_query_related_people_control(self, _):
        results = self._query()

        assert len(results) == 2
        ids = self._get_person_ids(results)
        assert str(self.person.uuid) in ids
        assert str(self.another_person.uuid) in ids

    @snapshot_clickhouse_queries
    @patch(f"{PATH}.posthoganalytics.feature_enabled", return_value=True)
    def test_query_related_people_optimized(self, _):
        results = self._query()

        assert len(results) == 2
        ids = self._get_person_ids(results)
        assert str(self.person.uuid) in ids
        assert str(self.another_person.uuid) in ids

    @parameterized.expand([("control", False), ("optimized", True)])
    @patch(f"{PATH}.posthoganalytics.feature_enabled")
    def test_returns_related_people(self, _name, flag_value, mock_flag):
        mock_flag.return_value = flag_value

        results = self._query()

        assert len(results) == 2
        ids = self._get_person_ids(results)
        assert str(self.person.uuid) in ids
        assert str(self.another_person.uuid) in ids
        assert str(self.unrelated_person.uuid) not in ids
        assert str(self.old_related_person.uuid) not in ids

    @parameterized.expand([("control", False), ("optimized", True)])
    @patch(f"{PATH}.posthoganalytics.feature_enabled")
    def test_excludes_deleted_person_mapping(self, _name, flag_value, mock_flag):
        mock_flag.return_value = flag_value
        self._insert_pdi2_row("user2", str(self.another_person.uuid), version=100, is_deleted=1)

        results = self._query()

        ids = self._get_person_ids(results)
        assert str(self.another_person.uuid) not in ids

    @parameterized.expand([("control", False), ("optimized", True)])
    @patch(f"{PATH}.posthoganalytics.feature_enabled")
    def test_reassigned_distinct_id_resolves_to_new_person(self, _name, flag_value, mock_flag):
        mock_flag.return_value = flag_value
        new_person = _create_person(distinct_ids=["new_user"], team=self.team, uuid=uuid4())
        flush_persons_and_events()
        self._insert_pdi2_row("user1", str(new_person.uuid), version=100)

        results = self._query()

        ids = self._get_person_ids(results)
        assert str(new_person.uuid) in ids
        assert str(self.person.uuid) not in ids

    @parameterized.expand([("control", False), ("optimized", True)])
    @patch(f"{PATH}.posthoganalytics.feature_enabled")
    def test_multiple_distinct_ids_same_person_deduped(self, _name, flag_value, mock_flag):
        mock_flag.return_value = flag_value
        self._insert_pdi2_row("user2", str(self.person.uuid), version=100)

        results = self._query()

        ids = self._get_person_ids(results)
        assert str(self.person.uuid) in ids
        assert len(ids) == 1
