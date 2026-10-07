from collections.abc import Callable
from dataclasses import field
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import get_candidate_relations_to_delete
from django.test import TestCase

from parameterized import parameterized

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.customer_analytics.backend.facade.membership_deletion_contracts import (
    MembershipDeletionKind,
    MembershipIdentity,
)
from products.customer_analytics.backend.logic.membership_deletion_receipts import (
    claim_membership_deletion,
    complete_membership_deletion,
    confirm_membership_deletion,
    get_membership_deletion,
    has_registered_membership_team,
    list_membership_deletion_identities,
    list_pending_membership_deletions,
    list_pending_preparations,
    prepare_membership_deletion,
    record_person_membership_deletion,
    register_membership_deletion_team,
    release_membership_deletion_claim,
)
from products.customer_analytics.backend.models.membership_deletion import (
    MembershipDeletionIdentity,
    MembershipDeletionReceipt,
    MembershipDeletionTeam,
)

if TYPE_CHECKING:
    from posthog.models.person.util import PersonTombstone


@frozen
class _TombstoneIdentity:
    id: str = field(repr=False)
    version: int


@frozen
class _CommittedTombstone:
    uuid: UUID = field(repr=False)
    version: int
    distinct_ids: tuple[_TombstoneIdentity, ...] = field(repr=False)


def _tombstone(*, version: int = 12, distinct_ids: tuple[_TombstoneIdentity, ...] | None = None) -> "PersonTombstone":
    return cast(
        "PersonTombstone",
        _CommittedTombstone(
            uuid=UUID("00000000-0000-0000-0000-000000000123"),
            version=version,
            distinct_ids=distinct_ids
            if distinct_ids is not None
            else (_TombstoneIdentity(id="synthetic-a", version=21), _TombstoneIdentity(id="synthetic-b", version=22)),
        ),
    )


class TestMembershipDeletionReceipts(TestCase):
    team_id = 98765001
    other_team_id = 98765002

    def setUp(self) -> None:
        super().setUp()
        register_membership_deletion_team(self.team_id)
        register_membership_deletion_team(self.other_team_id)

    @parameterized.expand([MembershipDeletionKind.TEAM, MembershipDeletionKind.TEAM_PERSONS])
    def test_preparation_confirmation_and_completion(self, kind: MembershipDeletionKind) -> None:
        receipt_id = prepare_membership_deletion(self.team_id, kind, "synthetic-request")
        assert prepare_membership_deletion(self.team_id, kind, "synthetic-request") == receipt_id
        assert not get_membership_deletion(self.team_id, receipt_id).confirmed
        assert [row.id for row in list_pending_preparations().receipts] == [receipt_id]
        assert list_pending_membership_deletions().receipts == ()
        with self.assertRaisesRegex(ValueError, "not confirmed"):
            complete_membership_deletion(self.team_id, receipt_id)
        confirm_membership_deletion(self.team_id, receipt_id)
        confirmed_at = get_membership_deletion(self.team_id, receipt_id).confirmed_at
        confirm_membership_deletion(self.team_id, receipt_id)
        assert get_membership_deletion(self.team_id, receipt_id).confirmed_at == confirmed_at
        assert list_pending_preparations().receipts == ()
        assert [row.id for row in list_pending_membership_deletions().receipts] == [receipt_id]
        complete_membership_deletion(self.team_id, receipt_id)
        completed_at = get_membership_deletion(self.team_id, receipt_id).completed_at
        complete_membership_deletion(self.team_id, receipt_id)
        assert get_membership_deletion(self.team_id, receipt_id).completed_at == completed_at
        assert prepare_membership_deletion(self.team_id, kind, "synthetic-request") == receipt_id
        assert list_pending_membership_deletions().receipts == ()

    def test_only_registered_teams_get_receipts(self) -> None:
        missing_team_id = 98765003
        assert not has_registered_membership_team(missing_team_id)
        with self.assertRaisesRegex(ValueError, "not registered"):
            prepare_membership_deletion(missing_team_id, MembershipDeletionKind.TEAM, "synthetic-request")
        register_membership_deletion_team(missing_team_id)
        register_membership_deletion_team(missing_team_id)
        assert has_registered_membership_team(missing_team_id)
        assert MembershipDeletionTeam.objects.for_team(missing_team_id).count() == 1

    def test_committed_tombstone_confirms_preparation_and_replays_without_reactivation(self) -> None:
        tombstone = _tombstone()
        receipt_id = prepare_membership_deletion(
            self.team_id, MembershipDeletionKind.PERSON, "synthetic-person", tombstone.uuid
        )
        with self.assertRaisesRegex(ValueError, "committed tombstone"):
            confirm_membership_deletion(self.team_id, receipt_id)
        assert record_person_membership_deletion(self.team_id, "synthetic-person", tombstone) == receipt_id
        details = get_membership_deletion(self.team_id, receipt_id)
        assert details.confirmed and details.person_version == 12 and details.person_uuid == tombstone.uuid
        rows = list_membership_deletion_identities(self.team_id, receipt_id).identities
        assert [row.identity for row in rows] == [
            MembershipIdentity(distinct_id="synthetic-a", version=21),
            MembershipIdentity(distinct_id="synthetic-b", version=22),
        ]
        assert record_person_membership_deletion(self.team_id, "synthetic-person", tombstone) == receipt_id
        assert list_membership_deletion_identities(self.team_id, receipt_id).identities == rows
        complete_membership_deletion(self.team_id, receipt_id)
        assert record_person_membership_deletion(self.team_id, "synthetic-person", tombstone) == receipt_id
        assert get_membership_deletion(self.team_id, receipt_id).completed
        assert list_membership_deletion_identities(self.team_id, receipt_id).identities == ()

    @parameterized.expand(
        [(False, "person"), (False, "identity"), (False, "set"), (True, "person"), (True, "identity"), (True, "set")]
    )
    def test_rejects_changed_tombstone_for_same_source(self, completed: bool, change: str) -> None:
        receipt_id = record_person_membership_deletion(self.team_id, "synthetic-person", _tombstone())
        if completed:
            complete_membership_deletion(self.team_id, receipt_id)
        if change == "person":
            changed = _tombstone(version=13)
        elif change == "identity":
            changed = _tombstone(
                distinct_ids=(
                    _TombstoneIdentity(id="synthetic-a", version=23),
                    _TombstoneIdentity(id="synthetic-b", version=22),
                )
            )
        else:
            changed = _tombstone(distinct_ids=(_TombstoneIdentity(id="synthetic-c", version=21),))
        with self.assertRaisesRegex(ValueError, "different tombstone"):
            record_person_membership_deletion(self.team_id, "synthetic-person", changed)
        assert get_membership_deletion(self.team_id, receipt_id).person_version == 12

    @parameterized.expand([False, True])
    def test_identity_failure_rolls_back_receipt_and_partial_rows(self, prepared: bool) -> None:
        tombstone = _tombstone(
            distinct_ids=tuple(_TombstoneIdentity(id=f"synthetic-{i}", version=i) for i in range(1001))
        )
        receipt_id = (
            prepare_membership_deletion(
                self.team_id, MembershipDeletionKind.PERSON, "synthetic-failure", tombstone.uuid
            )
            if prepared
            else None
        )
        inserts = 0

        def fail_second_identity_insert(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: dict[str, object]
        ) -> object:
            nonlocal inserts
            if sql.startswith("INSERT") and MembershipDeletionIdentity._meta.db_table in sql:
                inserts += 1
                if inserts == 2:
                    raise IntegrityError("synthetic storage failure")
            return execute(sql, params, many, context)

        with connection.execute_wrapper(fail_second_identity_insert):
            with self.assertRaisesRegex(IntegrityError, "synthetic storage failure"):
                record_person_membership_deletion(self.team_id, "synthetic-failure", tombstone)
        assert MembershipDeletionIdentity.objects.for_team(self.team_id).count() == 0
        assert list_pending_membership_deletions().receipts == ()
        if receipt_id is not None:
            assert not get_membership_deletion(self.team_id, receipt_id).confirmed
            assert [row.id for row in list_pending_preparations().receipts] == [receipt_id]
        else:
            assert list_pending_preparations().receipts == ()
        recovered_id = record_person_membership_deletion(self.team_id, "synthetic-failure", tombstone)
        assert receipt_id is None or recovered_id == receipt_id
        assert get_membership_deletion(self.team_id, recovered_id).confirmed
        assert MembershipDeletionIdentity.objects.for_team(self.team_id).count() == 1001

    def test_completion_and_receipt_access_stay_tenant_scoped(self) -> None:
        receipt_id = record_person_membership_deletion(self.team_id, "synthetic-person", _tombstone())
        other_id = record_person_membership_deletion(self.other_team_id, "synthetic-person", _tombstone())
        other_rows = list_membership_deletion_identities(self.other_team_id, other_id).identities
        operations: list[Callable[[int, UUID], object]] = [
            get_membership_deletion,
            confirm_membership_deletion,
            complete_membership_deletion,
            list_membership_deletion_identities,
        ]
        for operation in operations:
            with self.assertRaises(LookupError):
                operation(self.other_team_id, receipt_id)
        complete_membership_deletion(self.team_id, receipt_id)
        assert list_membership_deletion_identities(self.team_id, receipt_id).identities == ()
        assert list_membership_deletion_identities(self.other_team_id, other_id).identities == other_rows
        assert not get_membership_deletion(self.other_team_id, other_id).completed

    def test_identity_keyset_pagination_and_reordered_duplicate_tombstone(self) -> None:
        tombstone = _tombstone()
        receipt_id = record_person_membership_deletion(self.team_id, "synthetic-person", tombstone)
        first = list_membership_deletion_identities(self.team_id, receipt_id, limit=1)
        assert first.next_cursor is not None
        second = list_membership_deletion_identities(self.team_id, receipt_id, after_id=first.next_cursor, limit=1)
        assert [row.identity.distinct_id for row in first.identities + second.identities] == [
            "synthetic-a",
            "synthetic-b",
        ]
        assert second.next_cursor is None
        reordered = _tombstone(
            distinct_ids=(
                _TombstoneIdentity(id="synthetic-b", version=22),
                _TombstoneIdentity(id="synthetic-a", version=21),
                _TombstoneIdentity(id="synthetic-a", version=21),
            )
        )
        assert record_person_membership_deletion(self.team_id, "synthetic-person", reordered) == receipt_id

    @parameterized.expand([False, True])
    def test_cross_team_discovery_pages_equal_timestamps(self, confirmed: bool) -> None:
        first_id = prepare_membership_deletion(self.team_id, MembershipDeletionKind.TEAM, "synthetic-first")
        second_id = prepare_membership_deletion(
            self.other_team_id, MembershipDeletionKind.TEAM_PERSONS, "synthetic-second"
        )
        created_at = get_membership_deletion(self.team_id, first_id).created_at
        MembershipDeletionReceipt.objects.for_team(self.other_team_id).filter(id=second_id).update(
            created_at=created_at
        )
        if confirmed:
            confirm_membership_deletion(self.team_id, first_id)
            confirm_membership_deletion(self.other_team_id, second_id)
        discover = list_pending_membership_deletions if confirmed else list_pending_preparations
        first = discover(limit=1)
        assert first.next_cursor is not None
        second = discover(after=first.next_cursor, limit=1)
        assert [row.id for row in first.receipts + second.receipts] == sorted([first_id, second_id])
        assert {row.team_id for row in first.receipts + second.receipts} == {self.team_id, self.other_team_id}
        assert second.next_cursor is None

    def test_receipts_have_no_team_cascade_and_work_for_missing_and_literal_environment_ids(self) -> None:
        receipt_models = {MembershipDeletionTeam, MembershipDeletionReceipt, MembershipDeletionIdentity}
        assert not receipt_models.intersection(
            relation.related_model for relation in get_candidate_relations_to_delete(Team._meta)
        )
        assert not Team.objects.filter(id__in=[self.team_id, self.other_team_id]).exists()
        with team_scope(self.team_id, canonical=True):
            child_id = record_person_membership_deletion(self.other_team_id, "synthetic-child", _tombstone())
            with self.assertRaises(TeamScopeError):
                MembershipDeletionReceipt.objects.all()
        assert get_membership_deletion(self.other_team_id, child_id).team_id == self.other_team_id
        assert MembershipDeletionReceipt.objects.for_team(self.team_id).count() == 0
        assert has_registered_membership_team(self.other_team_id)
        complete_membership_deletion(self.other_team_id, child_id)
        assert get_membership_deletion(self.other_team_id, child_id).completed

    @parameterized.expand(
        [
            (MembershipDeletionKind.TEAM, None),
            (MembershipDeletionKind.PERSON, UUID("00000000-0000-0000-0000-000000000123")),
        ]
    )
    def test_database_source_uniqueness_handles_null_person_uuid(
        self, kind: MembershipDeletionKind, person_uuid: UUID | None
    ) -> None:
        prepare_membership_deletion(self.team_id, kind, "synthetic-unique", person_uuid)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MembershipDeletionReceipt.objects.for_team(self.team_id).create(
                team_id=self.team_id, kind=kind.value, source_key="synthetic-unique", person_uuid=person_uuid
            )

    def test_dispatch_capacity_is_shared_across_teams_and_completion_releases_it(self) -> None:
        first = prepare_membership_deletion(self.team_id, MembershipDeletionKind.TEAM, "first")
        second = prepare_membership_deletion(self.other_team_id, MembershipDeletionKind.TEAM, "second")
        confirm_membership_deletion(self.team_id, first)
        confirm_membership_deletion(self.other_team_id, second)
        assert claim_membership_deletion(self.team_id, first, max_running=1)
        assert claim_membership_deletion(self.team_id, first, max_running=1)
        assert not claim_membership_deletion(self.other_team_id, second, max_running=1)
        assert [reference.id for reference in list_pending_membership_deletions().receipts] == [second]
        complete_membership_deletion(self.team_id, first)
        assert claim_membership_deletion(self.other_team_id, second, max_running=1)

    def test_failed_dispatch_is_deferred_without_blocking_other_receipts(self) -> None:
        first = prepare_membership_deletion(self.team_id, MembershipDeletionKind.TEAM, "first")
        second = prepare_membership_deletion(self.other_team_id, MembershipDeletionKind.TEAM, "second")
        confirm_membership_deletion(self.team_id, first)
        confirm_membership_deletion(self.other_team_id, second)
        assert claim_membership_deletion(self.team_id, first, max_running=1)
        release_membership_deletion_claim(self.team_id, first)
        assert not claim_membership_deletion(self.team_id, first, max_running=1)
        assert [reference.id for reference in list_pending_membership_deletions().receipts] == [second]
        assert claim_membership_deletion(self.other_team_id, second, max_running=1)

    def test_receipt_and_identity_representations_hide_identifiers(self) -> None:
        receipt_id = record_person_membership_deletion(self.team_id, "synthetic-private-source", _tombstone())
        details = get_membership_deletion(self.team_id, receipt_id)
        assert "synthetic-private-source" not in repr(details)
        assert str(details.person_uuid) not in repr(details)
        assert "synthetic-a" not in repr(list_membership_deletion_identities(self.team_id, receipt_id))
