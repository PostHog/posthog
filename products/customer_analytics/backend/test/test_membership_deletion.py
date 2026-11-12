import logging
import traceback
from collections.abc import Callable
from datetime import timedelta
from time import monotonic

import pytest
from time_machine import travel
from unittest.mock import MagicMock, patch

from django.test import override_settings

from clickhouse_driver import Client
from clickhouse_driver.errors import ServerException, SocketTimeoutError
from parameterized import parameterized
from redis.exceptions import LockNotOwnedError

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ConnectionInfo
from posthog.clickhouse.workload import Workload

from products.customer_analytics.backend.logic.membership import MembershipKey, get_membership_cleanup_lease
from products.customer_analytics.backend.logic.membership_deletion import (
    SOCKET_TIMEOUT_SECONDS,
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

    @parameterized.expand([("single", 1, 400000), ("batch", 25, 12000)])
    def test_large_group_keys_do_not_block_membership_erasure(self, _: str, count: int, key_length: int) -> None:
        self.create_mapping(self.create_person())
        self.create_membership()
        surviving_key = MembershipKey(
            group_type_index=0, group_key="surviving-account", distinct_id=self.key.distinct_id
        )
        self.create_group(surviving_key.group_key)
        self.create_membership(surviving_key)
        for index in range(count):
            self.create_membership(
                MembershipKey(
                    group_type_index=0,
                    group_key=f"large-account-{index}-" + "a" * key_length,
                    distinct_id=self.key.distinct_id,
                )
            )
        self.run_discovery()
        candidates = MembershipCleanupCandidate.objects.for_team(self.team.pk)
        candidates.update(first_missing_at=self.now - timedelta(days=2))
        with patch.dict(
            "products.customer_analytics.backend.logic.membership.QUERY_SETTINGS", {"max_query_size": "65536"}
        ):
            result = self.run_deletion()
        assert result.deleted == count + 1
        assert result.failed_batches == 0
        assert not candidates.exists()
        assert sync_execute(
            "SELECT group_type_index, group_key, distinct_id FROM person_group_membership WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
            workload=Workload.OFFLINE,
        ) == [(surviving_key.group_type_index, surviving_key.group_key, surviving_key.distinct_id)]

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
        self.assert_membership_state(before, [])

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
                result = self.run_deletion()
                assert result.deleted == 0
                assert result.failed_batches == 1
            assert self.get_rows() == []
            assert MembershipCleanupCandidate.objects.for_team(self.team.pk).count() == 2
            assert self.run_deletion().deleted == 1
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    @parameterized.expand([("verify_membership_erasure",), ("verify_team_empty",)])
    def test_stalled_verification_preserves_cleanup_state(self, stage: str) -> None:
        self.create_membership()
        self.run_discovery()
        MembershipCleanupCandidate.objects.for_team(self.team.pk).update(first_missing_at=self.now - timedelta(days=2))
        timeouts: list[int | None] = []

        def stalled_query(*args: object, send_receive_timeout: int | None = None, **kwargs: object) -> None:
            timeouts.append(send_receive_timeout)
            raise SocketTimeoutError("verification stalled")

        with patch(
            "products.customer_analytics.backend.logic.membership_deletion.sync_execute", side_effect=stalled_query
        ):
            if stage == "verify_team_empty":
                with self.assertRaisesRegex(RuntimeError, stage):
                    self.store.has_membership(self.team.pk)
            else:
                assert self.run_deletion().failed_batches == 1
        assert timeouts == [SOCKET_TIMEOUT_SECONDS]
        assert self.store.timings.failed_step == stage
        assert MembershipCleanupCandidate.objects.for_team(self.team.pk).count() == 2
        assert MembershipCleanupScan.objects.for_team(self.team.pk).exists()

    @parameterized.expand([("lease",), ("deadline",)])
    def test_lost_lease_preserves_candidates_and_scan_position(self, failure: str) -> None:
        self.create_membership()
        self.run_discovery()
        MembershipCleanupCandidate.objects.for_team(self.team.pk).update(first_missing_at=self.now - timedelta(days=2))
        candidates = list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values())
        lease = get_membership_cleanup_lease(self.team.pk)

        with patch(
            "products.customer_analytics.backend.logic.membership_deletion.get_membership_cleanup_lease",
            return_value=lease,
        ):
            if failure == "deadline":
                self.store.deadline = monotonic() - 1
                error_type: type[Exception] = TimeoutError
                extension = patch.object(lease, "extend", wraps=lease.extend)
            else:
                original_extend = lease.extend

                def extend_lost_lease(*args: object, **kwargs: object) -> bool:
                    lease.redis.delete(lease.name)
                    return original_extend(60, replace_ttl=True)

                extension = patch.object(lease, "extend", side_effect=extend_lost_lease)
                error_type = LockNotOwnedError
            with extension, self.assertRaises(error_type):
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


@pytest.mark.parametrize("state", ["pending", "absent", "present", "survivors"])
def test_mutation_retry_does_not_resubmit_pending_or_completed_deletes(state: str) -> None:
    client = MagicMock()
    client.execute.side_effect = {
        "pending": [[(1,)]],
        "absent": [[(0,)], []],
        "present": [[(0,)], [(1,)], []],
        "survivors": [[(0,)], [(1,)], []],
    }[state]
    placement = MagicMock()
    placement.cluster.shards = [1]

    def dispatch(delete: Callable[[object], None], **kwargs: object) -> MagicMock:
        delete(client)
        return MagicMock()

    placement.cluster.map_one_host_per_shard.side_effect = dispatch
    key = MembershipKey(group_type_index=0, group_key="test-account", distinct_id="test-person")
    store = MembershipDeletionStore()
    with (
        patch("products.customer_analytics.backend.logic.membership_deletion._get_cleanup_cluster"),
        patch("products.customer_analytics.backend.logic.membership_deletion.placement_for", return_value=placement),
        patch(
            "products.customer_analytics.backend.logic.membership_deletion.sync_execute",
            return_value=[(int(state == "survivors"),)],
        ),
    ):
        if state == "pending":
            with pytest.raises(RuntimeError, match="check_pending_mutations"):
                store.delete_keys(1, [key])
            assert store.timings.failed_step == "check_pending_mutations"
        elif state == "survivors":
            with pytest.raises(RuntimeError, match="verify_membership_erasure"):
                store.delete_keys(1, [key])
            assert store.timings.failed_step == "verify_membership_erasure"
        else:
            store.delete_keys(1, [key])
    deletes = [call for call in client.execute.call_args_list if call.args[0].startswith("DELETE FROM")]
    assert len(deletes) == (1 if state in ("present", "survivors") else 0)
    if deletes:
        assert deletes[0].kwargs["settings"]["lightweight_deletes_sync"] == "2"


@pytest.mark.parametrize(
    "stage", ["read_erasure_targets", "delete_membership", "verify_membership_erasure", "verify_team_empty"]
)
def test_query_failures_do_not_expose_membership_identifiers(stage: str, caplog: pytest.LogCaptureFixture) -> None:
    identifier = "private-membership-identifier"
    error = ServerException(f"Query size exceeded near {identifier}", code=62)
    client = MagicMock()
    client.execute.side_effect = [
        [(0,)],
        error if stage == "read_erasure_targets" else [(1,)],
        error if stage == "delete_membership" else [],
    ]
    placement = MagicMock()
    placement.cluster.shards = [1]

    def dispatch(delete: Callable[[object], None], **kwargs: object) -> MagicMock:
        try:
            delete(client)
        except Exception:
            logging.getLogger("membership-dispatch-test").exception("Dispatcher failed")
            raise
        return MagicMock()

    placement.cluster.map_one_host_per_shard.side_effect = dispatch
    store = MembershipDeletionStore()
    with (
        patch("products.customer_analytics.backend.logic.membership_deletion._get_cleanup_cluster"),
        patch("products.customer_analytics.backend.logic.membership_deletion.placement_for", return_value=placement),
        patch("products.customer_analytics.backend.logic.membership_deletion.sync_execute", side_effect=error),
        pytest.raises(RuntimeError) as raised,
    ):
        if stage == "verify_team_empty":
            store.has_membership(1)
        else:
            store.delete_keys(1, [MembershipKey(group_type_index=0, group_key=identifier, distinct_id=identifier)])
    assert identifier not in "".join(traceback.format_exception(raised.value))
    assert identifier not in caplog.text
    assert store.timings.failed_step == stage


@override_settings(CLICKHOUSE_CLUSTER="posthog", CLICKHOUSE_AUX_CLUSTER="auxiliary")
@pytest.mark.parametrize("stage,elapsed", [("initial", 0), ("sibling", 2), ("expired", 5)])
def test_topology_discovery_obeys_remaining_batch_deadline(stage: str, elapsed: int) -> None:
    bootstrap = Client("example.invalid")
    pool = MagicMock()
    pool.get_client.return_value.__enter__.return_value.execute.return_value = [(0,)]
    queried_clusters: list[str] = []

    with (
        patch("products.customer_analytics.backend.logic.membership.monotonic", return_value=0),
        patch("posthog.clickhouse.cluster.time.monotonic", return_value=0) as clock,
        patch("posthog.clickhouse.cluster.default_client", return_value=bootstrap),
        patch.object(ConnectionInfo, "make_pool", return_value=pool),
    ):

        def stalled_discovery(query: str, params: dict[str, str]) -> list[tuple[str, int, int, int, str, str]]:
            queried_clusters.append(params["name"])
            if params["name"] == "posthog" and stage != "initial":
                clock.return_value = elapsed
                return [("main", 9000, 1, 1, "offline", "data")]
            assert 0 < bootstrap.connection.send_receive_timeout <= 5 - elapsed
            assert 0 < bootstrap.connection.connect_timeout <= 5 - elapsed
            assert 0 < bootstrap.connection.sync_request_timeout <= 5 - elapsed
            assert 0 < float(bootstrap.settings["max_execution_time"]) <= 5 - elapsed
            raise SocketTimeoutError("topology discovery stalled")

        with (
            patch.object(bootstrap, "execute", side_effect=stalled_discovery),
            pytest.raises(TimeoutError if stage == "expired" else SocketTimeoutError),
        ):
            MembershipDeletionStore(deadline=5).delete_keys(
                1, [MembershipKey(group_type_index=0, group_key="example-account", distinct_id="example-person")]
            )
    assert queried_clusters == (["posthog", "auxiliary"] if stage == "sibling" else ["posthog"])


@override_settings(CLICKHOUSE_CLUSTER="posthog", CLICKHOUSE_AUX_CLUSTER="auxiliary")
def test_deletion_refreshes_sibling_shards_between_batches() -> None:
    hosts = {
        "posthog": [("main", 9000, 1, 1, "offline", "data")],
        "auxiliary": [("aux-one", 9000, 1, 1, "offline", "aux")],
    }
    remaining = {"aux-one"}
    bootstrap = MagicMock()
    bootstrap.execute.side_effect = lambda query, params: hosts[params["name"]]

    def make_pool(connection: ConnectionInfo, *args: object, **kwargs: object) -> MagicMock:
        def execute(query: str, *args: object, **kwargs: object) -> list[tuple[int]]:
            if "system.tables" in query:
                return [(int(connection.host.startswith("aux-")),)]
            if "system.mutations" in query:
                return [(0,)]
            if query.startswith("DELETE FROM"):
                remaining.discard(connection.host)
                return []
            return [(1,)] if connection.host in remaining else []

        pool = MagicMock()
        pool.get_client.return_value.__enter__.return_value.execute.side_effect = execute
        return pool

    key = MembershipKey(group_type_index=0, group_key="example-account", distinct_id="example-person")
    store = MembershipDeletionStore()
    with (
        patch("posthog.clickhouse.cluster.default_client", return_value=bootstrap),
        patch.object(ConnectionInfo, "make_pool", autospec=True, side_effect=make_pool),
        patch(
            "products.customer_analytics.backend.logic.membership_deletion.sync_execute",
            side_effect=lambda *args, **kwargs: [(len(remaining),)],
        ),
    ):
        store.delete_keys(1, [key])
        assert remaining == set()
        hosts["auxiliary"].append(("aux-two", 9000, 2, 1, "offline", "aux"))
        remaining.add("aux-two")
        store.delete_keys(1, [key])
        assert remaining == set()
