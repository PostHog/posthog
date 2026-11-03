from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from time_machine import travel
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.customer_analytics.backend.logic.membership import MembershipKey
from products.customer_analytics.backend.logic.membership_cleanup import (
    MembershipCleanupCounts,
    MembershipCleanupInput,
    MembershipCleanupStore,
    list_membership_cleanup_teams,
    run_membership_cleanup,
)
from products.customer_analytics.backend.models.membership_cleanup import (
    MembershipCleanupCandidate,
    MembershipCleanupScan,
)


@pytest.mark.usefixtures("membership_cleanup_tables")
class TestMembershipCleanup(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.store = MembershipCleanupStore()
        self.key = MembershipKey(group_type_index=0, group_key="example-account", distinct_id="example-person")

    def create_membership(self, key: MembershipKey | None = None, team_id: int | None = None) -> None:
        key = key or self.key
        sync_execute(
            """INSERT INTO sharded_person_group_membership
            (team_id, group_type_index, group_key, distinct_id, first_seen, last_seen) VALUES""",
            [
                (
                    team_id or self.team.pk,
                    key.group_type_index,
                    key.group_key,
                    key.distinct_id,
                    self.now - timedelta(days=120),
                    self.now,
                )
            ],
        )

    def create_person(self, *, deleted: bool = False) -> UUID:
        person_id = uuid4()
        sync_execute(
            "INSERT INTO person (id, created_at, team_id, is_deleted, version) VALUES",
            [(person_id, self.now, self.team.pk, deleted, 1)],
        )
        return person_id

    def create_mapping(
        self, person_id: UUID, *, distinct_id: str | None = None, version: int = 1, deleted: bool = False
    ) -> None:
        sync_execute(
            "INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version) VALUES",
            [(self.team.pk, distinct_id or self.key.distinct_id, person_id, deleted, version)],
        )

    def create_group(self) -> None:
        sync_execute(
            "INSERT INTO groups (team_id, group_type_index, group_key, created_at, group_properties) VALUES",
            [(self.team.pk, self.key.group_type_index, self.key.group_key, self.now, "{}")],
        )

    def run_cleanup(self, *, dry_run: bool = False, allow_delete: bool = True) -> MembershipCleanupCounts:
        return run_membership_cleanup(
            MembershipCleanupInput(
                team_id=self.team.pk, dry_run=dry_run, delete_team_ids=(self.team.pk,) if allow_delete else ()
            ),
            self.store,
        )

    def get_rows(self, team_id: int | None = None) -> list[tuple[str]]:
        return sync_execute(
            "SELECT distinct_id FROM person_group_membership WHERE team_id = %(team_id)s ORDER BY distinct_id",
            {"team_id": team_id or self.team.pk},
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
            self.run_cleanup()
        candidate = MembershipCleanupCandidate.objects.for_team(self.team.pk).get()
        assert candidate.missing_side == missing_side
        assert candidate.first_missing_at == self.now
        with travel(self.now + timedelta(hours=23), tick=False):
            self.run_cleanup()
        assert self.get_rows() == [(self.key.distinct_id,)]
        candidate.refresh_from_db()
        assert candidate.first_missing_at == self.now
        with travel(self.now + timedelta(hours=24), tick=False):
            assert self.run_cleanup().deleted == 1
        assert self.get_rows() == []
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    @parameterized.expand([("person", False), ("person", True), ("group", False)])
    def test_recovered_match_clears_candidate(self, missing_side: str, reassigned_mapping: bool) -> None:
        self.create_membership()
        if missing_side == "person":
            self.create_group()
            if reassigned_mapping:
                self.create_mapping(self.create_person(deleted=True))
        else:
            self.create_mapping(self.create_person())
        with travel(self.now, tick=False):
            self.run_cleanup()
        if missing_side == "person":
            self.create_mapping(self.create_person(), version=2)
        else:
            self.create_group()
        with travel(self.now + timedelta(hours=25), tick=False):
            assert self.run_cleanup().recovered == 1
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    @parameterized.expand([(True, True), (False, False)])
    def test_deletion_requires_both_controls(self, dry_run: bool, allow_delete: bool) -> None:
        self.create_membership()
        with travel(self.now, tick=False):
            self.run_cleanup()
        with travel(self.now + timedelta(days=2), tick=False):
            assert self.run_cleanup(dry_run=dry_run, allow_delete=allow_delete).deleted == 0
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert MembershipCleanupCandidate.objects.for_team(self.team.pk).count() == 2

    def test_lookup_failure_preserves_candidates_and_cursor(self) -> None:
        self.create_membership()
        with travel(self.now, tick=False):
            self.run_cleanup()
        before = list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values())
        with patch(
            "products.customer_analytics.backend.logic.membership_cleanup.get_membership_existence",
            side_effect=RuntimeError("lookup unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "lookup unavailable"):
                self.run_cleanup()
        assert list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values()) == before
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert MembershipCleanupScan.objects.for_team(self.team.pk).get().cursor == []

    def test_failed_verification_keeps_candidates_for_retry(self) -> None:
        self.create_membership()
        with travel(self.now, tick=False):
            self.run_cleanup()
        delete_keys = self.store.delete_keys

        def delete_without_confirmation(team_id: int, keys: list[MembershipKey]) -> None:
            delete_keys(team_id, keys)
            raise RuntimeError("confirmation unavailable")

        with travel(self.now + timedelta(days=2), tick=False):
            with patch.object(self.store, "delete_keys", side_effect=delete_without_confirmation):
                assert self.run_cleanup().deleted == 0
            assert self.get_rows() == []
            assert MembershipCleanupCandidate.objects.for_team(self.team.pk).count() == 2
            assert self.run_cleanup().deleted == 1
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    def test_persisted_cursor_and_recreation(self) -> None:
        self.create_membership()
        other = MembershipKey(group_type_index=0, group_key="later-account", distinct_id="later-person")
        self.create_membership(other)
        with patch("products.customer_analytics.backend.logic.membership_cleanup.BATCH_SIZE", 1):
            self.run_cleanup(dry_run=True)
            scan = MembershipCleanupScan.objects.for_team(self.team.pk).get()
            assert scan.cursor == [self.key.group_type_index, self.key.group_key, self.key.distinct_id]
            run_membership_cleanup(MembershipCleanupInput(team_id=self.team.pk), MembershipCleanupStore())
            scan.refresh_from_db()
            assert scan.cursor == [other.group_type_index, other.group_key, other.distinct_id]
        with travel(self.now + timedelta(days=2), tick=False):
            self.run_cleanup()
        assert self.get_rows() == []
        self.now += timedelta(seconds=1)
        self.create_membership()
        self.create_group()
        self.create_mapping(self.create_person())
        self.run_cleanup()
        assert self.get_rows() == [(self.key.distinct_id,)]

    def test_deleted_team_cleanup_also_removes_config(self) -> None:
        deleted_team_id = self.team.pk + 1000000
        self.create_membership(team_id=deleted_team_id)
        sync_execute(
            "INSERT INTO person_group_membership_config (team_id, group_type_index, enabled, version) VALUES",
            [(deleted_team_id, 0, 1, 1)],
        )
        assert deleted_team_id in list_membership_cleanup_teams(self.store)
        input = MembershipCleanupInput(team_id=deleted_team_id, dry_run=False, delete_team_ids=(deleted_team_id,))
        with travel(self.now, tick=False):
            run_membership_cleanup(input, self.store)
        with travel(self.now + timedelta(days=2), tick=False):
            assert run_membership_cleanup(input, self.store).deleted == 1
        assert self.get_rows(deleted_team_id) == []
        assert sync_execute(
            "SELECT count() FROM distributed_person_group_membership_config WHERE team_id = %(team_id)s",
            {"team_id": deleted_team_id},
        ) == [(0,)]
        run_membership_cleanup(input, self.store)
        assert not MembershipCleanupScan.objects.for_team(deleted_team_id).exists()

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
            self.run_cleanup()
        delete_keys = self.store.delete_keys

        def delete_with_new_membership(team_id: int, keys: list[MembershipKey]) -> None:
            self.create_membership(other)
            delete_keys(team_id, keys)

        with travel(self.now + timedelta(days=2), tick=False):
            with patch.object(self.store, "delete_keys", side_effect=delete_with_new_membership):
                self.run_cleanup()
        assert self.get_rows() == [(other.distinct_id,)]
        assert sync_execute(
            "SELECT count() FROM distributed_person_group_membership_config WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        ) == [(1,)]
