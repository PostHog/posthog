from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.management.commands.fix_orphaned_ch_persons import run as run_orphan_repair
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

    def _stored(self, uuid: str) -> tuple[bool, int] | None:
        person = get_active_fake().stored_person(self.team.pk, uuid)
        return None if person is None else (person.is_deleted, person.version)

    def test_orphan_gets_a_persons_db_tombstone_above_clickhouse_and_disappears(self):
        uuid = str(uuid4())
        self._seed_ch_only_person(uuid, ["did-a", "did-b"], version=5)

        orphans = find_orphaned_ch_persons(self.team.pk, [uuid])
        assert [(o.uuid, o.ch_max_version) for o in orphans] == [(uuid, 5)]

        result = tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=False)

        assert (result.tombstoned_persons, result.republished_persons, result.skipped_live_persons) == (1, 0, 0)
        assert self._stored(uuid) == (True, 6)
        assert self._ch_person_state(uuid) == (1, 6)
        assert find_orphaned_ch_persons(self.team.pk, [uuid]) == []
        # The ClickHouse deletion sweep removes these with their deleted owner, so the repair writes no mapping row.
        for did in ("did-a", "did-b"):
            assert self._ch_mapping_state(did) == (uuid, 0, 0)

    @parameterized.expand(
        [
            # (name, ClickHouse max version, persons-DB version expected after the repair)
            ("at_or_above_clickhouse", 0, None),
            ("below_a_live_clickhouse_row", 7, 8),
        ]
    )
    def test_person_tombstoned_in_the_persons_db_is_raised_above_clickhouse_and_republished(
        self, _name: str, ch_max_version: int, raised_to: int | None
    ):
        person = create_person(team=self.team, distinct_ids=["did-t"], properties={})
        [written] = tombstone_persons_in_postgres(self.team.pk, [person.uuid])
        if ch_max_version:
            create_person_in_ch(uuid=str(person.uuid), team_id=self.team.pk, version=ch_max_version, is_deleted=False)
        # The fake still reads tombstoned persons, so the orphan is built the way a real read reports it.
        orphan = OrphanedPerson(uuid=str(person.uuid), ch_max_version=ch_max_version, created_at=person.created_at)

        result = tombstone_orphaned_ch_persons(self.team.pk, [orphan], dry_run=False)

        version = raised_to or written.version
        assert (result.republished_persons, result.tombstoned_persons) == (1, 0)
        assert self._stored(str(person.uuid)) == (True, version)
        assert self._ch_person_state(str(person.uuid)) == (1, version)
        assert self._ch_mapping_state("did-t")[1:] == (1, written.distinct_ids[0].version)

    def test_live_person_reported_as_orphan_by_a_lagging_read_is_left_alone(self):
        person = create_person(team=self.team, distinct_ids=["did-l"], properties={})
        orphan = OrphanedPerson(uuid=str(person.uuid), ch_max_version=0, created_at=person.created_at)

        result = tombstone_orphaned_ch_persons(self.team.pk, [orphan], dry_run=False)

        assert (result.skipped_live_persons, result.tombstoned_persons, result.republished_persons) == (1, 0, 0)
        assert get_person_tombstones(self.team.pk, [person.uuid]) == []
        assert self._ch_person_state(str(person.uuid))[0] == 0

    def test_a_rerun_after_a_failed_publish_republishes_the_tombstone_it_inserted(self):
        uuid = str(uuid4())
        self._seed_ch_only_person(uuid, ["did-o"], version=2)
        orphans = find_orphaned_ch_persons(self.team.pk, [uuid])

        with (
            patch("posthog.models.person.util.publish_person_tombstone", side_effect=RuntimeError("kafka down")),
            self.assertRaises(RuntimeError),
        ):
            tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=False)
        assert self._stored(uuid) == (True, 3)
        assert self._ch_person_state(uuid) == (0, 2)

        # The rerun finds the tombstone it inserted and still publishes it.
        result = tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=False)

        assert result.republished_persons == 1
        assert self._ch_person_state(uuid) == (1, 3)

    def test_a_failed_batch_leaves_earlier_batches_published(self):
        uuids = [str(uuid4()), str(uuid4())]
        for uuid in uuids:
            self._seed_ch_only_person(uuid, [], version=2)
        orphans = find_orphaned_ch_persons(self.team.pk, uuids)
        fake = get_active_fake()
        ensure_floors = fake.ensure_person_version_floors
        requests = []

        def fail_the_second_batch(request, timeout=None):
            requests.append(request)
            if len(requests) == 2:
                raise RuntimeError("personhog down")
            return ensure_floors(request, timeout)

        with (
            patch("posthog.models.person.deletion.PERSONHOG_BATCH_SIZE", 1),
            patch.object(fake, "ensure_person_version_floors", side_effect=fail_the_second_batch),
            self.assertRaises(RuntimeError),
        ):
            tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=False)

        first, second = (r.floors[0].person_uuid for r in requests)
        assert (self._stored(first), self._ch_person_state(first)) == ((True, 3), (1, 3))
        assert (self._stored(second), self._ch_person_state(second)) == (None, (0, 2))

    def test_dry_run_writes_nothing(self):
        uuid = str(uuid4())
        self._seed_ch_only_person(uuid, ["did-a"], version=3)
        orphans = find_orphaned_ch_persons(self.team.pk, [uuid])

        result = tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=True)

        assert (result.dry_run, result.tombstoned_persons) == (True, 1)
        assert self._ch_person_state(uuid) == (0, 3)
        assert self._stored(uuid) is None
        assert not [c for c in get_active_fake().calls if c.method == "ensure_person_version_floors"]

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
            # (name, how the shared distinct_id's ClickHouse winner looks)
            ("self_owned_live", None),
            ("reassigned_to_live_other", "live_other"),
            ("reverse_drift_db_live", "deleted_mapping_of_live_person"),
        ]
    )
    def test_mappings_are_left_alone_and_reverse_drift_is_reported(self, _name: str, other: str | None):
        orphan_uuid = str(uuid4())
        shared_did = "shared-did"
        self._seed_ch_only_person(orphan_uuid, [shared_did], version=5)
        other_uuid = None
        if other == "live_other":
            other_uuid = str(uuid4())
            create_person_distinct_id(
                team_id=self.team.pk, distinct_id=shared_did, person_id=other_uuid, version=1, is_deleted=False
            )
        elif other == "deleted_mapping_of_live_person":
            other_uuid = str(create_person(team=self.team, distinct_ids=["other-did"], properties={}).uuid)
            create_person_distinct_id(
                team_id=self.team.pk, distinct_id=shared_did, person_id=other_uuid, version=1, is_deleted=True
            )
        before = self._ch_mapping_state(shared_did)

        orphans = find_orphaned_ch_persons(self.team.pk, [orphan_uuid])
        result = tombstone_orphaned_ch_persons(self.team.pk, orphans, dry_run=False)

        assert result.tombstoned_persons == 1
        assert self._ch_mapping_state(shared_did) == before
        expected_drift = [(shared_did, other_uuid)] if other == "deleted_mapping_of_live_person" else []
        assert result.reverse_drift_mappings == expected_drift

    @parameterized.expand(
        [
            # (name, other live ClickHouse persons, --force, expect the repair to run)
            ("over_the_limit_is_refused", 0, False, False),
            ("force_overrides_the_limit", 0, True, True),
            ("within_the_limit_runs", 20, False, True),
        ]
    )
    def test_the_command_refuses_to_tombstone_a_large_share_of_a_team(
        self, _name: str, others: int, force: bool, expect_repair: bool
    ):
        uuid = str(uuid4())
        self._seed_ch_only_person(uuid, ["did-a"], version=5)
        for _ in range(others):
            self._seed_ch_only_person(str(uuid4()), [], version=1)
        options = {"team_id": self.team.pk, "person_uuid": [uuid], "all": False, "dry_run": False, "force": force}

        if expect_repair:
            run_orphan_repair(options)
        else:
            with self.assertRaises(SystemExit):
                run_orphan_repair(options)

        assert self._stored(uuid) == ((True, 6) if expect_repair else None)
        assert self._ch_person_state(uuid) == ((1, 6) if expect_repair else (0, 5))
