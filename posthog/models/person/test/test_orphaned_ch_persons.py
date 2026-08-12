from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.person.deletion import find_orphaned_ch_persons, tombstone_orphaned_ch_persons
from posthog.models.person.util import (
    create_person as create_person_in_ch,
    create_person_distinct_id,
)
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

    def test_dry_run_produces_nothing(self):
        uuid = str(uuid4())
        self._seed_ch_only_person(uuid, ["did-a"], version=3)
        orphans = find_orphaned_ch_persons(self.team.pk, [uuid])
        result = tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=True)

        # Counts reflect what would happen...
        assert result.dry_run is True
        assert result.tombstoned_persons == 1
        assert result.tombstoned_mappings == 1
        # ...but ClickHouse is untouched.
        is_deleted, version = self._ch_person_state(uuid)
        assert is_deleted == 0
        assert version == 3

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
