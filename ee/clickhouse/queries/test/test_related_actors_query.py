from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import cast
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

from posthog.clickhouse.client import sync_execute
from posthog.models import Group, GroupTypeMapping
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.util import create_group

from ee.clickhouse.queries.related_actors_query import RelatedActorsQuery

RECENT_DATE = datetime(2025, 2, 15, 12, 0, 0)


class BaseRelatedActorsTest(ABC, ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.person = _create_person(distinct_ids=["user1"], team=self.team)
        self.another_person = _create_person(distinct_ids=["user2"], team=self.team)
        self.unrelated_person = _create_person(distinct_ids=["user3"], team=self.team)
        self.old_related_person = _create_person(distinct_ids=["user4"], team=self.team)

        self.org_group_type = GroupTypeMapping.objects.create(
            group_type_index=0, team=self.team, project=self.project, group_type="org"
        )
        self.instance_group_type = GroupTypeMapping.objects.create(
            group_type_index=1, team=self.team, project=self.project, group_type="instance"
        )
        org_type_index = cast(GroupTypeIndex, self.org_group_type.group_type_index)
        instance_type_index = cast(GroupTypeIndex, self.instance_group_type.group_type_index)

        self.org1 = create_group(
            team_id=self.team.id,
            group_type_index=org_type_index,
            group_key="org:1",
            properties={"name": "org 1"},
        )
        self.another_org = create_group(
            team_id=self.team.id,
            group_type_index=org_type_index,
            group_key="another-org",
            properties={"name": "another org"},
        )
        self.instance = create_group(
            team_id=self.team.id,
            group_type_index=instance_type_index,
            group_key="instance:1",
            properties={"name": "instance 1"},
        )

        self._create_group_event("user1", RECENT_DATE, self.org1)
        self._create_group_event("user1", RECENT_DATE, self.instance)
        self._create_group_event("user2", RECENT_DATE, self.org1)
        self._create_group_event("user3", RECENT_DATE, self.another_org)
        self._create_group_event("user4", RECENT_DATE - timedelta(days=100), self.org1)
        flush_persons_and_events()

    def _create_group_event(self, distinct_id: str, timestamp: datetime, group: Group) -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={f"$group_{group.group_type_index}": group.group_key},
        )

    def _insert_pdi2_row(self, distinct_id: str, person_id: str, version: int, is_deleted: int = 0) -> None:
        sync_execute(
            "INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version) VALUES",
            [(self.team.pk, distinct_id, person_id, is_deleted, version)],
        )

    @staticmethod
    def get_ids_from_results(results: list) -> set[str]:
        return {r["id"] for r in results}

    @abstractmethod
    def run_query(self) -> list:
        raise NotImplementedError()


@freeze_time("2025-03-01T12:00:00Z")
class TestRelatedPersonsQuery(BaseRelatedActorsTest):
    def run_query(self) -> list:
        return RelatedActorsQuery(team=self.team, group_type_index=0, id="org:1").run()

    @snapshot_clickhouse_queries
    def test_query_related_people(self):
        results = self.run_query()

        assert len(results) == 2
        ids = self.get_ids_from_results(results)
        assert str(self.person.uuid) in ids
        assert str(self.another_person.uuid) in ids

    def test_returns_related_people(self):
        results = self.run_query()

        assert len(results) == 2
        ids = self.get_ids_from_results(results)
        assert str(self.person.uuid) in ids
        assert str(self.another_person.uuid) in ids
        assert str(self.unrelated_person.uuid) not in ids
        assert str(self.old_related_person.uuid) not in ids

    def test_excludes_deleted_person_mapping(self):
        self._insert_pdi2_row("user2", str(self.another_person.uuid), version=100, is_deleted=1)

        results = self.run_query()

        ids = self.get_ids_from_results(results)
        assert str(self.another_person.uuid) not in ids

    def test_reassigned_distinct_id_resolves_to_new_person(self):
        new_person = _create_person(distinct_ids=["new_user"], team=self.team, uuid=uuid4())
        flush_persons_and_events()
        self._insert_pdi2_row("user1", str(new_person.uuid), version=100)

        results = self.run_query()

        ids = self.get_ids_from_results(results)
        assert str(new_person.uuid) in ids
        assert str(self.person.uuid) not in ids

    def test_multiple_distinct_ids_same_person_deduped(self):
        self._insert_pdi2_row("user2", str(self.person.uuid), version=100)

        results = self.run_query()

        ids = self.get_ids_from_results(results)
        assert str(self.person.uuid) in ids
        assert len(ids) == 1


@freeze_time("2025-03-01T12:00:00Z")
class TestRelatedGroupsQuery(BaseRelatedActorsTest):
    def run_query(self) -> list:
        return RelatedActorsQuery(team=self.team, group_type_index=None, id=str(self.person.uuid)).run()

    @snapshot_clickhouse_queries
    def test_query(self):
        results = self.run_query()

        assert len(results) == 2
        ids = self.get_ids_from_results(results)
        assert ids == {"org:1", "instance:1"}

    def test_returns_related_groups(self):
        results = self.run_query()

        ids = self.get_ids_from_results(results)
        assert "org:1" in ids
        assert "instance:1" in ids

    def test_excludes_unrelated_groups(self):
        results = self.run_query()

        ids = self.get_ids_from_results(results)
        assert "another-org" not in ids

    def test_excludes_old_groups(self):
        results = self.run_query()

        ids = self.get_ids_from_results(results)
        assert str(self.old_related_person.uuid) not in ids

    def test_returns_all_groups_of_same_type(self):
        extra_org = create_group(
            team_id=self.team.id,
            group_type_index=cast(GroupTypeIndex, self.org_group_type.group_type_index),
            group_key="org:2",
            properties={"name": "org 2"},
        )
        self._create_group_event("user1", RECENT_DATE, extra_org)
        flush_persons_and_events()

        results = self.run_query()

        ids = self.get_ids_from_results(results)
        assert "org:1" in ids
        assert "org:2" in ids
        assert "instance:1" in ids

    def test_no_groups_when_no_mappings(self):
        another_team = self.create_team_with_organization(self.organization)
        another_person = _create_person(team=another_team, uuid=uuid4())

        results = RelatedActorsQuery(team=another_team, group_type_index=None, id=str(another_person.uuid)).run()

        group_results = [r for r in results if r.get("type") == "group"]
        assert len(group_results) == 0
