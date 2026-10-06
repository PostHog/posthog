from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized

from posthog.schema import PersonsOnEventsMode

from posthog.clickhouse.client import sync_execute
from posthog.models import Group
from posthog.models.event.util import create_event
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.util import create_group
from posthog.test.persons import create_group_type_mapping

from ee.clickhouse.queries.related_actors_query import RelatedActorsQuery

RECENT_DATE = datetime(2025, 2, 15, 12, 0, 0)


class BaseRelatedActorsTest(ABC, ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.person = _create_person(distinct_ids=["user1"], team=self.team)
        self.another_person = _create_person(distinct_ids=["user2"], team=self.team)
        self.unrelated_person = _create_person(distinct_ids=["user3"], team=self.team)
        self.old_related_person = _create_person(distinct_ids=["user4"], team=self.team)

        self.org_group_type = create_group_type_mapping(
            group_type_index=0, team=self.team, project=self.project, group_type="org"
        )
        self.instance_group_type = create_group_type_mapping(
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


@time_machine.travel("2025-03-01T12:00:00Z", tick=False)
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


@time_machine.travel("2025-03-01T12:00:00Z", tick=False)
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


@time_machine.travel("2025-03-01T12:00:00Z", tick=False)
class TestRelatedGroupsPersonIdentity(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS}
        create_group_type_mapping(group_type_index=0, team=self.team, project=self.project, group_type="company")

    def _record_group_visit(self, *, distinct_id: str, stored_person_id: UUID, group_key: str) -> None:
        create_group(team_id=self.team.pk, group_type_index=0, group_key=group_key)
        create_event(
            event_uuid=uuid4(),
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            person_id=stored_person_id,
            timestamp=RECENT_DATE.replace(tzinfo=UTC),
            properties={"$group_0": group_key},
        )

    def _set_override(self, distinct_id: str, person_id: UUID, *, version: int, is_deleted: bool = False) -> None:
        sync_execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted) VALUES",
            [(self.team.pk, distinct_id, str(person_id), version, int(is_deleted))],
        )

    def _related_group_keys(self, person_id: UUID) -> set[str]:
        results = RelatedActorsQuery(team=self.team, group_type_index=None, id=str(person_id)).run()
        return {str(group["id"]) for group in results}

    @parameterized.expand(
        [
            ("merged_id_still_mapped", ["current-id", "historical-id"]),
            ("detached_id_no_longer_mapped", ["current-id"]),
        ]
    )
    def test_override_preserves_historical_group_with_or_without_current_mapping(
        self, _case: str, current_distinct_ids: list[str]
    ) -> None:
        person = _create_person(team=self.team, distinct_ids=current_distinct_ids)
        previous_owner_id = uuid4()
        self._record_group_visit(
            distinct_id="historical-id", stored_person_id=previous_owner_id, group_key="historical-company"
        )
        self._set_override("historical-id", person.uuid, version=1)

        assert self._related_group_keys(person.uuid) == {"historical-company"}

    def test_squashed_history_still_returns_the_historical_group_without_an_override(self) -> None:
        person = _create_person(team=self.team, distinct_ids=["current-id"])
        self._record_group_visit(
            distinct_id="detached-id", stored_person_id=person.uuid, group_key="historical-company"
        )

        assert self._related_group_keys(person.uuid) == {"historical-company"}

    def test_group_follows_the_new_owner_after_a_newer_override(self) -> None:
        previous_owner = _create_person(team=self.team, distinct_ids=["previous-owner-id"])
        new_owner = _create_person(team=self.team, distinct_ids=["new-owner-id"])
        self._record_group_visit(
            distinct_id="transferred-id", stored_person_id=previous_owner.uuid, group_key="transferred-company"
        )
        self._set_override("transferred-id", previous_owner.uuid, version=1)
        self._set_override("transferred-id", new_owner.uuid, version=2)

        assert self._related_group_keys(previous_owner.uuid) == set()
        assert self._related_group_keys(new_owner.uuid) == {"transferred-company"}

    def test_deleting_an_override_returns_the_group_to_the_stored_owner(self) -> None:
        stored_owner = _create_person(team=self.team, distinct_ids=["stored-owner-id"])
        override_owner = _create_person(team=self.team, distinct_ids=["override-owner-id"])
        self._record_group_visit(
            distinct_id="restored-id", stored_person_id=stored_owner.uuid, group_key="restored-company"
        )
        self._set_override("restored-id", override_owner.uuid, version=1)
        self._set_override("restored-id", override_owner.uuid, version=2, is_deleted=True)

        assert self._related_group_keys(stored_owner.uuid) == {"restored-company"}
        assert self._related_group_keys(override_owner.uuid) == set()

    def test_reusing_a_distinct_id_does_not_share_groups_between_people(self) -> None:
        current_owner = _create_person(team=self.team, distinct_ids=["reused-id"])
        previous_owner = _create_person(team=self.team, distinct_ids=["previous-owner-id"])
        self._record_group_visit(
            distinct_id="reused-id", stored_person_id=current_owner.uuid, group_key="current-owner-company"
        )
        self._record_group_visit(
            distinct_id="reused-id", stored_person_id=previous_owner.uuid, group_key="previous-owner-company"
        )

        assert self._related_group_keys(current_owner.uuid) == {"current-owner-company"}
        assert self._related_group_keys(previous_owner.uuid) == {"previous-owner-company"}

    def test_group_from_the_last_of_2501_override_candidates_is_not_lost(self) -> None:
        person = _create_person(team=self.team, distinct_ids=["current-id"])
        historical_ids = [f"historical-{index:04d}" for index in range(2501)]
        sync_execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version) VALUES",
            [(self.team.pk, distinct_id, str(person.uuid), 1) for distinct_id in historical_ids],
        )
        self._record_group_visit(
            distinct_id=historical_ids[-1], stored_person_id=uuid4(), group_key="last-historical-company"
        )

        assert self._related_group_keys(person.uuid) == {"last-historical-company"}

    @parameterized.expand(
        [
            (PersonsOnEventsMode.DISABLED, {"current-mapping-company"}),
            (PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS, {"stored-owner-company"}),
            (
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                {"stored-owner-company", "override-company"},
            ),
            (PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED, {"stored-owner-company", "override-company"}),
        ]
    )
    def test_project_identity_mode_decides_which_groups_belong_to_the_person(
        self, mode: PersonsOnEventsMode, expected_groups: set[str]
    ) -> None:
        self.team.modifiers = {"personsOnEventsMode": mode}
        person = _create_person(team=self.team, distinct_ids=["mapped-to-person-id"])
        other_person = _create_person(team=self.team, distinct_ids=["stored-with-person-id", "overridden-to-person-id"])
        self._record_group_visit(
            distinct_id="mapped-to-person-id", stored_person_id=other_person.uuid, group_key="current-mapping-company"
        )
        self._record_group_visit(
            distinct_id="stored-with-person-id", stored_person_id=person.uuid, group_key="stored-owner-company"
        )
        self._record_group_visit(
            distinct_id="overridden-to-person-id", stored_person_id=other_person.uuid, group_key="override-company"
        )
        self._set_override("overridden-to-person-id", person.uuid, version=1)

        assert self._related_group_keys(person.uuid) == expected_groups

    def test_event_history_returns_groups_even_without_a_person_record(self) -> None:
        event_only_person_id = uuid4()
        self._record_group_visit(
            distinct_id="event-only-id", stored_person_id=event_only_person_id, group_key="event-only-company"
        )

        assert self._related_group_keys(event_only_person_id) == {"event-only-company"}
