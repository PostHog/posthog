from collections.abc import Callable
from datetime import timedelta
from time import monotonic

import pytest
from time_machine import travel
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.customer_analytics.backend.logic.membership import MembershipKey
from products.customer_analytics.backend.logic.membership_deletion import (
    MembershipDeletionCounts,
    MembershipDeletionInput,
    MembershipDeletionStore,
    list_membership_deletion_teams,
    record_membership_deletion_team,
    run_membership_deletion,
)
from products.customer_analytics.backend.logic.membership_discovery import (
    MembershipDiscoveryInput,
    MembershipDiscoveryStore,
    list_membership_discovery_teams,
    record_membership_discovery_team,
    run_membership_discovery,
)
from products.customer_analytics.backend.models.membership_cleanup import (
    MembershipCleanupCandidate,
    MembershipCleanupScan,
)
from products.customer_analytics.backend.test.membership_test_utils import MembershipTestCase


@pytest.mark.usefixtures("membership_cleanup_tables")
class TestMembershipDeletion(MembershipTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = MembershipDeletionStore()

    def run_discovery(self) -> None:
        run_membership_discovery(MembershipDiscoveryInput(team_id=self.team.pk), MembershipDiscoveryStore())

    def run_deletion(self, *, dry_run: bool = False, allow_delete: bool = True) -> MembershipDeletionCounts:
        return run_membership_deletion(
            MembershipDeletionInput(
                team_id=self.team.pk, dry_run=dry_run, delete_team_ids=(self.team.pk,) if allow_delete else ()
            ),
            self.store,
        )

    @parameterized.expand(
        [("person", False, False), ("person", True, False), ("person", False, True), ("group", False, False)]
    )
    def test_grace_period_and_physical_erasure(
        self, missing_side: str, deleted_profile: bool, deleted_mapping: bool
    ) -> None:
        self.create_membership()
        if missing_side == "person":
            self.create_group()
            if deleted_profile or deleted_mapping:
                person_id = self.create_person(deleted=deleted_profile)
                self.create_mapping(person_id)
                if deleted_mapping:
                    self.create_mapping(person_id, version=2, deleted=True)
        else:
            self.create_mapping(self.create_person())
        with travel(self.now, tick=False):
            self.run_discovery()
        candidate = MembershipCleanupCandidate.objects.for_team(self.team.pk).get()
        assert candidate.missing_side == missing_side
        assert candidate.first_missing_at == self.now
        with travel(self.now + timedelta(hours=23), tick=False):
            self.run_deletion()
        assert self.get_rows() == [(self.key.distinct_id,)]
        candidate.refresh_from_db()
        assert candidate.first_missing_at == self.now
        with travel(self.now + timedelta(hours=24), tick=False):
            assert self.run_deletion().deleted == 1
        assert self.get_rows() == []
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    @parameterized.expand([("person", False), ("person", True), ("group", False)])
    def test_recovered_match_clears_candidate(self, missing_side: str, reassigned_mapping: bool) -> None:
        self.restore_missing_membership(missing_side, reassigned_mapping)
        with travel(self.now + timedelta(hours=25), tick=False):
            assert self.run_deletion().recovered == 1
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    @parameterized.expand([(True, True), (False, False)])
    def test_deletion_requires_both_controls(self, dry_run: bool, allow_delete: bool) -> None:
        self.create_membership()
        with travel(self.now, tick=False):
            self.run_discovery()
        with travel(self.now + timedelta(days=2), tick=False):
            assert self.run_deletion(dry_run=dry_run, allow_delete=allow_delete).deleted == 0
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert MembershipCleanupCandidate.objects.for_team(self.team.pk).count() == 2

    def test_lookup_failure_preserves_candidates_and_cursor(self) -> None:
        self.create_membership()
        with travel(self.now, tick=False):
            self.run_discovery()
        MembershipCleanupCandidate.objects.for_team(self.team.pk).update(first_missing_at=self.now - timedelta(days=2))
        before = list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values())
        with patch(
            "products.customer_analytics.backend.logic.membership_deletion.get_membership_existence",
            side_effect=RuntimeError("lookup unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "lookup unavailable"):
                self.run_deletion()
        assert list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values()) == before
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert MembershipCleanupScan.objects.for_team(self.team.pk).get().cursor == []

    @parameterized.expand([("live",), ("deleted_mapping",), ("deleted_person",), ("orphan",), ("unavailable",)])
    def test_primary_identity_check_protects_membership(self, identity_state: str) -> None:
        self.create_membership()
        self.create_group()
        with travel(self.now, tick=False):
            self.run_discovery()
        with self.primary_person_lookup(identity_state):
            if identity_state == "unavailable":
                with self.assertRaisesRegex(RuntimeError, "identity unavailable"):
                    self.run_deletion()
            else:
                result = self.run_deletion()
                assert result.deleted == (0 if identity_state == "live" else 1)
                assert result.recovered == (1 if identity_state == "live" else 0)
        if identity_state in ("live", "unavailable"):
            assert self.get_rows() == [(self.key.distinct_id,)]
            assert MembershipCleanupCandidate.objects.for_team(self.team.pk).exists() == (
                identity_state == "unavailable"
            )
        else:
            assert self.get_rows() == []

    @parameterized.expand([("live",), ("missing",), ("unavailable",)])
    def test_primary_group_check_protects_membership(self, group_state: str) -> None:
        self.key = MembershipKey(group_type_index=0, group_key=r"account \"north\"", distinct_id=self.key.distinct_id)
        self.create_membership()
        self.create_mapping(self.create_person())
        self.run_discovery()
        candidates = MembershipCleanupCandidate.objects.for_team(self.team.pk)
        before = list(candidates.values())
        with self.primary_group_lookup(group_state):
            if group_state == "unavailable":
                with self.assertRaisesRegex(RuntimeError, "group lookup unavailable"):
                    self.run_deletion()
                assert list(candidates.values()) == before
            else:
                result = self.run_deletion()
                assert result.deleted == (1 if group_state == "missing" else 0)
                assert result.recovered == (1 if group_state == "live" else 0)
                assert not candidates.exists()
        assert self.get_rows() == ([] if group_state == "missing" else [(self.key.distinct_id,)])

    def test_failed_verification_keeps_candidates_for_retry(self) -> None:
        self.create_membership()
        with travel(self.now, tick=False):
            self.run_discovery()
        delete_keys = self.store.delete_keys

        def delete_without_confirmation(team_id: int, keys: list[MembershipKey]) -> None:
            delete_keys(team_id, keys)
            raise RuntimeError("confirmation unavailable")

        with travel(self.now + timedelta(days=2), tick=False):
            with patch.object(self.store, "delete_keys", side_effect=delete_without_confirmation):
                assert self.run_deletion().deleted == 0
            assert self.get_rows() == []
            assert MembershipCleanupCandidate.objects.for_team(self.team.pk).count() == 2
            assert self.run_deletion().deleted == 1
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    @parameterized.expand([("lease",), ("deadline",)])
    def test_lost_lease_preserves_candidates_and_scan_position(self, failure: str) -> None:
        self.create_membership()
        self.run_discovery()
        MembershipCleanupCandidate.objects.for_team(self.team.pk).update(first_missing_at=self.now - timedelta(days=2))
        candidates = list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values())
        with patch("products.customer_analytics.backend.logic.membership.get_redis_client") as redis:
            lease = redis.return_value.lock.return_value
            if failure == "deadline":
                self.store.deadline = monotonic() - 1
                error_type = TimeoutError
            else:
                lease.extend.side_effect = RuntimeError("lease lost")
                error_type = RuntimeError
            with self.assertRaises(error_type):
                self.run_deletion()
        assert list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values()) == candidates
        assert MembershipCleanupScan.objects.for_team(self.team.pk).get().cursor == []
        assert self.get_rows() == [(self.key.distinct_id,)]

    def test_person_purge_keeps_config_and_concurrent_membership(self) -> None:
        self.create_membership()
        sync_execute(
            "INSERT INTO person_group_membership_config (team_id, group_type_index, enabled, version) VALUES",
            [(self.team.pk, 0, 0, 1)],
        )
        other = MembershipKey(group_type_index=0, group_key=self.key.group_key, distinct_id="surviving-person")
        self.create_group()
        self.create_mapping(self.create_person(), distinct_id=other.distinct_id)
        with travel(self.now, tick=False):
            self.run_discovery()
        delete_keys = self.store.delete_keys

        def delete_with_new_membership(team_id: int, keys: list[MembershipKey]) -> None:
            self.create_membership(other)
            delete_keys(team_id, keys)

        with travel(self.now + timedelta(days=2), tick=False):
            with patch.object(self.store, "delete_keys", side_effect=delete_with_new_membership):
                self.run_deletion()
        assert self.get_rows() == [(other.distinct_id,)]
        assert sync_execute(
            "SELECT count() FROM distributed_person_group_membership_config WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        ) == [(1,)]

    def test_deletion_does_not_discover_missing_identities(self) -> None:
        self.create_membership()
        assert self.run_deletion().checked == 0
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    def test_deletion_preserves_discovery_cursor_until_it_advances(self) -> None:
        other = MembershipKey(group_type_index=0, group_key="later-account", distinct_id="later-person")
        self.create_membership()
        self.create_membership(other)
        self.run_discovery()
        MembershipCleanupCandidate.objects.for_team(self.team.pk).update(first_missing_at=self.now - timedelta(days=2))
        with patch("products.customer_analytics.backend.logic.membership_discovery.BATCH_SIZE", 1):
            self.run_discovery()
            scan = MembershipCleanupScan.objects.for_team(self.team.pk).get()
            cursor = [other.group_type_index, other.group_key, other.distinct_id]
            assert scan.cursor == cursor
            assert self.run_deletion().deleted == 1
            scan.refresh_from_db()
            assert scan.cursor == cursor
            assert self.get_rows() == [(other.distinct_id,)]
            self.run_discovery()
        assert self.run_deletion().deleted == 1
        assert self.get_rows() == []

    def test_deleted_team_erasure_removes_config_and_scan(self) -> None:
        team_id = self.team.pk + 1000000
        self.create_membership(team_id=team_id)
        sync_execute(
            "INSERT INTO person_group_membership_config (team_id, group_type_index, enabled, version) VALUES",
            [(team_id, 0, 1, 1)],
        )
        run_membership_discovery(MembershipDiscoveryInput(team_id=team_id), MembershipDiscoveryStore())
        MembershipCleanupCandidate.objects.for_team(team_id).update(first_missing_at=self.now - timedelta(days=2))
        with patch(
            "products.customer_analytics.backend.logic.membership_deletion.get_membership_existence",
            side_effect=RuntimeError("identity unavailable"),
        ):
            assert (
                run_membership_deletion(
                    MembershipDeletionInput(team_id=team_id, dry_run=False, delete_team_ids=(team_id,)), self.store
                ).deleted
                == 1
            )
        assert self.get_rows(team_id) == []
        assert not MembershipCleanupCandidate.objects.for_team(team_id).exists()
        assert not MembershipCleanupScan.objects.for_team(team_id).exists()
        assert sync_execute(
            "SELECT count() FROM distributed_person_group_membership_config WHERE team_id = %(team_id)s",
            {"team_id": team_id},
        ) == [(0,)]

    def test_coordinators_keep_separate_team_cursors(self) -> None:
        self.create_membership()
        other_team_id = self.team.pk + 1000000
        self.create_membership(team_id=other_team_id)
        discovery_store = MembershipDiscoveryStore()
        run_membership_discovery(MembershipDiscoveryInput(team_id=self.team.pk), discovery_store)
        run_membership_discovery(MembershipDiscoveryInput(team_id=other_team_id), discovery_store)
        MembershipCleanupCandidate.objects.unscoped().update(first_missing_at=self.now - timedelta(days=2))
        assert list_membership_discovery_teams(discovery_store) == [self.team.pk, other_team_id]
        record_membership_discovery_team(self.team.pk)
        assert list_membership_deletion_teams() == [self.team.pk, other_team_id]
        record_membership_deletion_team(self.team.pk)
        assert list_membership_discovery_teams(discovery_store) == [other_team_id]
        assert list_membership_deletion_teams() == [other_team_id]
        record_membership_deletion_team(other_team_id)
        assert list_membership_deletion_teams() == []
        assert list_membership_deletion_teams() == [self.team.pk, other_team_id]


@pytest.mark.parametrize("state", ["pending", "absent", "present"])
def test_mutation_retry_does_not_resubmit_pending_or_completed_deletes(state: str) -> None:
    client = MagicMock()
    client.execute.side_effect = {
        "pending": [[(1,)]],
        "absent": [[(0,)], []],
        "present": [[(0,)], [(1,)], []],
    }[state]
    placement = MagicMock()
    placement.cluster.shards = [1]

    def dispatch(delete: Callable[[object], None], **kwargs: object) -> MagicMock:
        delete(client)
        return MagicMock()

    placement.cluster.map_one_host_per_shard.side_effect = dispatch
    key = MembershipKey(group_type_index=0, group_key="test-account", distinct_id="test-person")
    with (
        patch("products.customer_analytics.backend.logic.membership_deletion._get_cleanup_cluster"),
        patch("products.customer_analytics.backend.logic.membership_deletion.placement_for", return_value=placement),
        patch("products.customer_analytics.backend.logic.membership_deletion.sync_execute", return_value=[(0,)]),
    ):
        if state == "pending":
            with pytest.raises(RuntimeError, match="pending mutation"):
                MembershipDeletionStore().delete_keys(1, [key])
        else:
            MembershipDeletionStore().delete_keys(1, [key])
    deletes = [call for call in client.execute.call_args_list if call.args[0].startswith("DELETE FROM")]
    assert len(deletes) == (1 if state == "present" else 0)
    if deletes:
        assert deletes[0].kwargs["settings"]["lightweight_deletes_sync"] == "2"
