from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.person.deletion import OrphanedPerson, find_orphaned_ch_persons, tombstone_orphaned_ch_persons
from posthog.models.person.util import (
    create_person as create_person_in_ch,
    create_person_distinct_id,
    get_person_tombstones,
    tombstone_persons_in_postgres,
)
from posthog.personhog_client.fake_client import get_active_fake
from posthog.test.persons import create_person


class TestOrphanedCHPersonRepair(ClickhouseTestMixin, BaseTest):
    def _seed_ch_only_person(self, uuid: str, distinct_ids: list[str], version: int = 5) -> None:
        # Live in ClickHouse, never seeded into the persons DB (fake) — an orphan.
        create_person_in_ch(
            uuid=uuid,
            team_id=self.team.pk,
            version=version,
            properties={"email": "orphan@example.com"},
            is_deleted=False,
        )
        for distinct_id in distinct_ids:
            create_person_distinct_id(
                team_id=self.team.pk, distinct_id=distinct_id, person_id=uuid, version=0, is_deleted=False
            )

    def _ch_person_state(self, uuid: str) -> tuple[int, int]:
        rows = sync_execute(
            "SELECT argMax(is_deleted, version), max(version) FROM person FINAL WHERE team_id = %(t)s AND id = %(u)s",
            {"t": self.team.pk, "u": uuid},
        )
        return int(rows[0][0]), int(rows[0][1])

    def _ch_mapping_state(self, distinct_id: str) -> tuple[str, int, int]:
        rows = sync_execute(
            """
            SELECT argMax(person_id, version), argMax(is_deleted, version), max(version)
            FROM person_distinct_id2 FINAL
            WHERE team_id = %(t)s AND distinct_id = %(d)s
            """,
            {"t": self.team.pk, "d": distinct_id},
        )
        return str(rows[0][0]), int(rows[0][1]), int(rows[0][2])

    def test_orphan_is_tombstoned_and_disappears(self):
        uuid = str(uuid4())
        self._seed_ch_only_person(uuid, ["did-a", "did-b"], version=5)

        orphans = find_orphaned_ch_persons(self.team.pk, [uuid])
        assert [o.uuid for o in orphans] == [uuid]
        assert orphans[0].ch_max_version == 5

        result = tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=False)

        assert result.tombstoned_persons == 1
        assert result.tombstoned_mappings == 2

        is_deleted, version = self._ch_person_state(uuid)
        assert is_deleted == 1
        assert version == 105  # ch_max_version + 100
        # Gone from the live-person read path.
        assert find_orphaned_ch_persons(self.team.pk, [uuid]) == []
        for did in ("did-a", "did-b"):
            _, mapping_deleted, _ = self._ch_mapping_state(did)
            assert mapping_deleted == 1

    @parameterized.expand([("dry_run", True), ("apply", False)])
    def test_person_tombstoned_in_the_persons_db_is_republished_at_its_stored_versions(self, _name: str, dry_run: bool):
        person = create_person(team=self.team, distinct_ids=["did-t"], properties={})
        [written] = tombstone_persons_in_postgres(self.team.pk, [person.uuid])
        # The fake still reads tombstoned persons, so the orphan is built the way a real read reports it.
        orphan = OrphanedPerson(uuid=str(person.uuid), ch_max_version=0, created_at=person.created_at)

        result = tombstone_orphaned_ch_persons(self.team.pk, [orphan], dry_run=dry_run)

        assert (result.republished_persons, result.tombstoned_persons) == (1, 0)
        if dry_run:
            assert self._ch_person_state(str(person.uuid))[0] == 0
            return
        assert self._ch_person_state(str(person.uuid)) == (1, written.version)
        assert self._ch_mapping_state("did-t")[1:] == (1, written.distinct_ids[0].version)

    def test_live_person_reported_as_orphan_by_a_lagging_read_stays_live_in_the_persons_db(self):
        person = create_person(team=self.team, distinct_ids=["did-l"], properties={})
        orphan = OrphanedPerson(uuid=str(person.uuid), ch_max_version=0, created_at=person.created_at)

        result = tombstone_orphaned_ch_persons(self.team.pk, [orphan], dry_run=False)

        assert (result.republished_persons, result.tombstoned_persons) == (0, 1)
        assert get_person_tombstones(self.team.pk, [person.uuid]) == []
        assert self._ch_person_state(str(person.uuid)) == (1, 100)

    def test_a_failed_republish_still_tombstones_the_true_orphans_mappings(self):
        orphan_uuid = str(uuid4())
        self._seed_ch_only_person(orphan_uuid, ["did-o"])
        person = create_person(team=self.team, distinct_ids=["did-t"], properties={})
        tombstone_persons_in_postgres(self.team.pk, [person.uuid])
        orphans = [
            *find_orphaned_ch_persons(self.team.pk, [orphan_uuid]),
            OrphanedPerson(uuid=str(person.uuid), ch_max_version=0, created_at=person.created_at),
        ]

        with (
            patch("posthog.models.person.util.publish_person_tombstone", side_effect=RuntimeError("kafka down")),
            self.assertRaises(RuntimeError),
        ):
            tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=False)

        # A rerun would not revisit this orphan, so its mapping has to be tombstoned on this run.
        assert self._ch_person_state(orphan_uuid)[0] == 1
        assert self._ch_mapping_state("did-o")[1] == 1

    def test_dry_run_produces_nothing(self):
        uuid = str(uuid4())
        self._seed_ch_only_person(uuid, ["did-a"], version=3)
        orphans = find_orphaned_ch_persons(self.team.pk, [uuid])
        result = tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=True)

        # Counts reflect what would happen...
        assert result.dry_run is True
        assert result.tombstoned_persons == 1
        assert result.tombstoned_mappings == 1
        # ...but ClickHouse and the persons DB are untouched.
        is_deleted, version = self._ch_person_state(uuid)
        assert is_deleted == 0
        assert version == 3
        assert not [c for c in get_active_fake().calls if c.method == "delete_persons"]

    def test_live_person_is_never_an_orphan(self):
        # A person present in the persons DB (seeded into the fake) must not be
        # reported as an orphan even when its uuid is passed explicitly.
        person = create_person(team=self.team, distinct_ids=["live-did"], properties={"email": "a@b.com"})

        orphans = find_orphaned_ch_persons(self.team.pk, [str(person.uuid)])
        assert orphans == []

        result = tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=False)

        assert result.tombstoned_persons == 0
        is_deleted, _ = self._ch_person_state(str(person.uuid))
        assert is_deleted == 0

    @parameterized.expand(
        [
            # (name, mapping outcome for the shared distinct_id)
            ("self_owned_live", "tombstone"),
            ("reassigned_to_live_other", "skip_reassigned"),
            ("reverse_drift_db_live", "reverse_drift"),
        ]
    )
    def test_mapping_classification(self, _name: str, outcome: str):
        orphan_uuid = str(uuid4())
        shared_did = "shared-did"

        self._seed_ch_only_person(orphan_uuid, [shared_did], version=5)

        other_uuid: str | None = None
        if outcome == "skip_reassigned":
            # A different, non-deleted CH mapping wins shared_did — reassigned.
            other_uuid = str(uuid4())
            create_person_distinct_id(
                team_id=self.team.pk,
                distinct_id=shared_did,
                person_id=other_uuid,
                version=1,
                is_deleted=False,
            )
        elif outcome == "reverse_drift":
            # A person live in the persons DB whose CH mapping for shared_did is
            # tombstoned — the opposite drift, reported not repaired.
            other = create_person(team=self.team, distinct_ids=["other-did"], properties={})
            other_uuid = str(other.uuid)
            create_person_distinct_id(
                team_id=self.team.pk,
                distinct_id=shared_did,
                person_id=other_uuid,
                version=1,
                is_deleted=True,
            )

        orphans = find_orphaned_ch_persons(self.team.pk, [orphan_uuid])
        result = tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=False)

        # The orphan person is always tombstoned regardless of mapping fate.
        assert result.tombstoned_persons == 1

        if outcome == "tombstone":
            assert result.tombstoned_mappings == 1
            assert result.skipped_reassigned_mappings == 0
            assert result.reverse_drift_mappings == []
            _, mapping_deleted, _ = self._ch_mapping_state(shared_did)
            assert mapping_deleted == 1
        elif outcome == "skip_reassigned":
            assert result.tombstoned_mappings == 0
            assert result.skipped_reassigned_mappings == 1
            assert result.reverse_drift_mappings == []
            winner, mapping_deleted, _ = self._ch_mapping_state(shared_did)
            assert winner == other_uuid  # untouched, still the live reassignment
            assert mapping_deleted == 0
        else:  # reverse_drift
            assert result.tombstoned_mappings == 0
            assert result.skipped_reassigned_mappings == 0
            assert result.reverse_drift_mappings == [(shared_did, other_uuid)]
