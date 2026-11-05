from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.management.commands.fix_orphaned_ch_persons import run as run_orphan_repair
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person.deletion import (
    OrphanedPerson,
    find_orphaned_ch_persons,
    plan_orphan_data_erasure,
    tombstone_orphaned_ch_persons,
)
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
        assert self._queued_event_deletions() == set()

    def _queued_event_deletions(self) -> set[str]:
        return set(
            AsyncDeletion.objects.filter(team_id=self.team.pk, deletion_type=DeletionType.Person).values_list(
                "key", flat=True
            )
        )

    def _seed_rest_of_team(self) -> None:
        # Keeps the repair under the share limit, so that limit cannot be what stops a run.
        for _ in range(20):
            self._seed_ch_only_person(str(uuid4()), [], version=1)

    def _erase(
        self, uuids: list[str], *, expect_exit: bool = False, **overrides: object
    ) -> tuple[list[str], MagicMock]:
        options = {
            "team_id": self.team.pk,
            "person_uuid": uuids,
            "all": False,
            "dry_run": False,
            "force": False,
            "delete_events": True,
            "delete_recordings": True,
            "reason": "erasure request",
            **overrides,
        }
        temporal = MagicMock()
        temporal.start_workflow = AsyncMock()
        with (
            patch("posthog.models.person.bulk_delete.sync_connect", return_value=temporal),
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion") as training,
        ):
            if expect_exit:
                with self.assertRaises(SystemExit):
                    run_orphan_repair(options)
            else:
                run_orphan_repair(options)
        inputs = [c.args[1] for c in temporal.start_workflow.call_args_list]
        assert all(i.config.deleted_by == "fix_orphaned_ch_persons" for i in inputs)
        return sorted(d for i in inputs for d in i.distinct_ids), training

    def test_erasure_reaches_repaired_orphans_and_spares_live_persons(self):
        orphan = str(uuid4())
        self._seed_ch_only_person(orphan, ["did-orphan"], version=5)
        self._seed_rest_of_team()
        live = create_person(team=self.team, distinct_ids=["did-live"], properties={})

        recording_ids, training = self._erase([orphan, str(live.uuid)])

        assert self._queued_event_deletions() == {orphan}
        assert recording_ids == ["did-orphan"]
        training.assert_called_once_with(self.team.pk, ["did-orphan"])

    def test_erasure_skips_a_distinct_id_a_live_person_owns(self):
        orphan = str(uuid4())
        self._seed_ch_only_person(orphan, ["did-own", "did-shared"], version=5)
        self._seed_rest_of_team()
        create_person(team=self.team, distinct_ids=["did-shared"], properties={})

        recording_ids, _training = self._erase([orphan])

        assert recording_ids == ["did-own"]

    def test_erasure_rerun_after_the_repair_still_queues_tombstoned_persons(self):
        orphan = str(uuid4())
        self._seed_ch_only_person(orphan, ["did-a"], version=5)
        self._seed_rest_of_team()
        self._erase([orphan], delete_events=False, delete_recordings=False)
        assert find_orphaned_ch_persons(self.team.pk, [orphan]) == []

        recording_ids, _training = self._erase([orphan])

        assert self._queued_event_deletions() == {orphan}
        assert recording_ids == ["did-a"]

    def _tombstoned_person_with_stored_distinct_id(self, distinct_id: str) -> str:
        person = create_person(team=self.team, distinct_ids=[distinct_id], properties={})
        tombstone_persons_in_postgres(self.team.pk, [person.uuid])
        orphan = OrphanedPerson(uuid=str(person.uuid), ch_max_version=0, created_at=person.created_at)
        tombstone_orphaned_ch_persons(self.team.pk, [orphan], dry_run=False)
        return str(person.uuid)

    def test_erasure_fails_loudly_when_it_cannot_tie_every_stored_distinct_id_to_the_person(self):
        uuid = self._tombstoned_person_with_stored_distinct_id("did-t")
        assert self._ch_mapping_state("did-t")[1] == 1

        recording_ids, training = self._erase([uuid], expect_exit=True)

        assert recording_ids == []
        training.assert_not_called()
        assert self._queued_event_deletions() == {uuid}

    def test_erasure_deletes_confirmed_distinct_ids_before_failing_on_unconfirmed_ones(self):
        uuid = self._tombstoned_person_with_stored_distinct_id("did-t")
        create_person_distinct_id(
            team_id=self.team.pk, distinct_id="did-mapped", person_id=uuid, version=0, is_deleted=False
        )

        recording_ids, training = self._erase([uuid], expect_exit=True)

        assert recording_ids == ["did-mapped"]
        training.assert_called_once_with(self.team.pk, ["did-mapped"])

    def test_erasure_of_events_alone_does_not_fail_on_unconfirmed_distinct_ids(self):
        uuid = self._tombstoned_person_with_stored_distinct_id("did-t")

        self._erase([uuid], delete_recordings=False, reason="")

        assert self._queued_event_deletions() == {uuid}

    def test_erasure_dry_run_shows_the_distinct_ids_a_real_run_cannot_confirm(self):
        uuid = self._tombstoned_person_with_stored_distinct_id("did-t")

        with patch("posthog.management.commands.fix_orphaned_ch_persons.logger") as logger:
            self._erase([uuid], dry_run=True)

        [erasure_log] = [c for c in logger.info.call_args_list if c.args == ("Orphan data erasure",)]
        assert erasure_log.kwargs["unconfirmed_distinct_ids"] == ["did-t"]

    def test_erasure_still_reports_stored_distinct_ids_after_the_sweep_removes_mappings(self):
        uuid = self._tombstoned_person_with_stored_distinct_id("did-t")
        sync_execute("TRUNCATE TABLE person_distinct_id2")

        plan = plan_orphan_data_erasure(self.team.pk, [uuid])

        assert (plan.recording_distinct_ids, plan.unconfirmed_distinct_ids) == ([], ["did-t"])

    def test_erasure_leaves_out_a_stored_distinct_id_that_another_person_now_holds(self):
        uuid = self._tombstoned_person_with_stored_distinct_id("did-t")
        create_person_distinct_id(
            team_id=self.team.pk, distinct_id="did-t", person_id=str(uuid4()), version=1000, is_deleted=False
        )

        plan = plan_orphan_data_erasure(self.team.pk, [uuid])

        assert (plan.recording_distinct_ids, plan.unconfirmed_distinct_ids) == ([], [])

    def test_erasure_dry_run_deletes_nothing(self):
        orphan = str(uuid4())
        self._seed_ch_only_person(orphan, ["did-a"], version=5)

        recording_ids, training = self._erase([orphan], dry_run=True)

        assert self._queued_event_deletions() == set()
        assert recording_ids == []
        training.assert_not_called()
        assert self._stored(orphan) is None

    @parameterized.expand(
        [
            # A dry run, because every person is an orphan under --all and a real run stops at the share limit first.
            ("all_persons", {"person_uuid": None, "all": True, "dry_run": True}),
            ("force", {"force": True}),
            ("recordings_without_a_reason", {"reason": ""}),
        ]
    )
    def test_erasure_refuses_unsafe_options(self, _name: str, overrides: dict[str, object]):
        orphan = str(uuid4())
        self._seed_ch_only_person(orphan, ["did-a"], version=5)
        self._seed_rest_of_team()

        with self.assertRaises(SystemExit):
            self._erase([orphan], **overrides)

        assert self._queued_event_deletions() == set()
        assert self._ch_person_state(orphan) == (0, 5)

    def test_erasure_over_the_share_limit_is_refused(self):
        orphan = str(uuid4())
        self._seed_ch_only_person(orphan, ["did-a"], version=5)

        with self.assertRaises(SystemExit):
            self._erase([orphan])

        assert self._queued_event_deletions() == set()
