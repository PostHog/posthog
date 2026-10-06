from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.models import QuerySet
from django.test import override_settings
from django.utils import timezone

from dagster import Failure, build_op_context
from parameterized import parameterized

from posthog.dags.data_deletion_requests import PersonRemovalContext, delete_person_profiles_op
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person import Person
from posthog.models.person.bulk_delete import PersonDeletionStep, delete_persons_profile
from posthog.models.person.util import get_person_tombstones
from posthog.models.team import Team
from posthog.models.team.util import delete_team_records
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.proto import (
    DeletePersonsMode,
    DeletePersonsRequest,
    DeletePersonsResponse,
    GetPersonsRequest,
)
from posthog.temporal.delete_persons.delete_persons_workflow import (
    _delete_specific_persons_via_personhog,
    _delete_team_persons_batch_via_personhog,
)

from products.customer_analytics.backend.facade.membership_deletion_contracts import MembershipDeletionKind
from products.customer_analytics.backend.logic.membership_deletion import (
    process_membership_deletion,
    recover_prepared_deletions,
    team_deletion_verified,
)
from products.customer_analytics.backend.logic.membership_deletion_receipts import (
    get_membership_deletion,
    list_membership_deletion_identities,
    register_membership_deletion_team,
)
from products.customer_analytics.backend.logic.membership_deletion_sources import MembershipDeletionSources
from products.customer_analytics.backend.models.membership_deletion import MembershipDeletionReceipt
from products.customer_analytics.backend.test.test_membership_deletion_worker import _cluster, _FakeClickHouse


@override_settings(CUSTOMER_ANALYTICS_MEMBERSHIP_DELETION_ENABLED=True)
class TestMembershipDeletionSources(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        register_membership_deletion_team(self.team.pk)

    def _profile(self, person_id: int, person_uuid: UUID, *distinct_ids: str) -> Person:
        person = Person(
            id=person_id,
            team_id=self.team.pk,
            uuid=person_uuid,
            created_at=timezone.now(),
        )
        person._distinct_ids = list(distinct_ids)
        return person

    def _receipt(self, person_uuid: UUID) -> MembershipDeletionReceipt:
        return MembershipDeletionReceipt.objects.for_team(self.team.pk).get(person_uuid=person_uuid)

    def _ids(self, receipt: MembershipDeletionReceipt) -> list[str]:
        return [
            row.identity.distinct_id for row in list_membership_deletion_identities(self.team.pk, receipt.id).identities
        ]

    def test_profile_deletion_finishes_before_background_membership_cleanup(self) -> None:
        person_uuid = uuid4()
        clickhouse = _FakeClickHouse(
            membership=[
                (self.team.pk, 0, "example-account", "a"),
                (self.team.pk, 0, "example-account", "alias"),
                (self.team.pk, 0, "example-account", "unrelated"),
            ]
        )
        with (
            fake_personhog_client() as fake,
            patch("posthog.models.person.util.publish_person_tombstone", return_value=[]),
            patch("posthog.clickhouse.cluster.default_client", side_effect=AssertionError("Unexpected discovery")),
        ):
            fake.add_person(team_id=self.team.pk, person_id=1, uuid=str(person_uuid), distinct_ids=["a", "alias"])
            result = delete_persons_profile(
                self.team.pk,
                [self._profile(1, person_uuid, "a", "alias")],
                actor=None,
                queue_ai_training_deletion=False,
            )
            assert result.deleted_count == 1
            assert result.failures == []
            assert not fake.get_persons(GetPersonsRequest(team_id=self.team.pk, person_ids=[1])).persons
            assert clickhouse.remaining(self.team.pk) == ["a", "alias", "unrelated"]
            receipt = self._receipt(person_uuid)
            assert receipt.confirmed_at is not None
            assert receipt.completed_at is None
            assert self._ids(receipt) == ["a", "alias"]
            process_membership_deletion(_cluster(clickhouse), self.team.pk, receipt.id)
        assert clickhouse.remaining(self.team.pk) == ["unrelated"]
        assert get_membership_deletion(self.team.pk, receipt.id).completed

    @parameterized.expand([("profile_helper", False), ("dagster_request", True)])
    def test_failed_intent_write_keeps_source_profile_and_does_not_report_success(
        self, _name: str, dagster: bool
    ) -> None:
        person_uuid = uuid4()
        with fake_personhog_client() as fake:
            fake.add_person(team_id=self.team.pk, person_id=1, uuid=str(person_uuid), distinct_ids=["a"])
            with (
                patch.object(QuerySet, "bulk_create", side_effect=RuntimeError("Receipt store unavailable")),
                patch("posthog.models.person.bulk_delete.queue_person_training_deletion"),
            ):
                if dagster:
                    request = PersonRemovalContext(
                        request_id=str(uuid4()),
                        team_id=self.team.pk,
                        person_uuids=[str(person_uuid)],
                        person_distinct_ids=[],
                        drop_profiles=True,
                        drop_events=False,
                        drop_recordings=False,
                    )
                    with self.assertRaisesRegex(Failure, "receipt preparation"):
                        delete_person_profiles_op(build_op_context(), request)
                else:
                    result = delete_persons_profile(
                        self.team.pk,
                        [self._profile(1, person_uuid, "a")],
                        actor=None,
                        queue_ai_training_deletion=False,
                    )
                    assert result.deleted_count == 0
                    assert [failure.step for failure in result.failures] == [
                        PersonDeletionStep.QUEUE_MEMBERSHIP_DELETION
                    ]
            assert fake.get_persons(GetPersonsRequest(team_id=self.team.pk, person_ids=[1])).persons
            fake.assert_not_called("delete_persons")

    def test_failed_postcommit_capture_keeps_intent_for_independent_recovery(self) -> None:
        person_uuid = uuid4()
        with (
            fake_personhog_client() as fake,
            patch("posthog.models.person.util.publish_person_tombstone", return_value=[]),
        ):
            fake.add_person(team_id=self.team.pk, person_id=1, uuid=str(person_uuid), distinct_ids=["a"])
            with patch.object(QuerySet, "bulk_update", side_effect=RuntimeError("Receipt store unavailable")):
                result = delete_persons_profile(
                    self.team.pk,
                    [self._profile(1, person_uuid, "a")],
                    actor=None,
                    queue_ai_training_deletion=False,
                )
            assert result.deleted_count == 1
            assert result.failures == []
            receipt = self._receipt(person_uuid)
            assert receipt.confirmed_at is None
            assert self._ids(receipt) == []
            recover_prepared_deletions(None)
        assert get_membership_deletion(self.team.pk, receipt.id).confirmed
        assert self._ids(receipt) == ["a"]

    def test_by_id_deletion_recovers_from_saved_uuid_without_bypassing_the_physical_drain(self) -> None:
        person_uuid = uuid4()
        with (
            fake_personhog_client() as fake,
            patch("posthog.models.person.util.publish_person_tombstone", return_value=[]),
        ):
            fake.add_person(team_id=self.team.pk, person_id=1, uuid=str(person_uuid), distinct_ids=["a"])
            with patch.object(QuerySet, "bulk_update", side_effect=RuntimeError("Receipt store unavailable")):
                with self.assertRaises(RuntimeError):
                    _delete_specific_persons_via_personhog(self.team.pk, [1], "example-purge")
            assert not fake.get_persons(GetPersonsRequest(team_id=self.team.pk, person_ids=[1])).persons
            assert get_person_tombstones(self.team.pk, [person_uuid])
            fake.assert_not_called("delete_tombstoned_persons")
            receipt = MembershipDeletionReceipt.objects.for_team(self.team.pk).get(
                person_uuid=person_uuid, source_key__startswith="purge:"
            )
            assert receipt.confirmed_at is None
            deleted = _delete_specific_persons_via_personhog(self.team.pk, [1], "example-purge")
            assert deleted == 0
            assert get_person_tombstones(self.team.pk, [person_uuid])
            fake.assert_not_called("delete_tombstoned_persons")
        assert get_membership_deletion(self.team.pk, receipt.id).confirmed
        assert self._ids(receipt) == ["a"]

    def test_by_id_deletion_records_aliases_from_the_committed_tombstone(self) -> None:
        person_uuid = uuid4()
        with (
            fake_personhog_client() as fake,
            patch("posthog.models.person.util.publish_person_tombstone", return_value=[]),
        ):
            fake.add_person(team_id=self.team.pk, person_id=1, uuid=str(person_uuid), distinct_ids=["a"])
            original = fake.delete_persons
            added = False

            def add_alias_before_tombstone(
                request: DeletePersonsRequest, timeout: float | None = None
            ) -> DeletePersonsResponse:
                nonlocal added
                if request.mode == DeletePersonsMode.DELETE_PERSONS_MODE_TOMBSTONE and not added:
                    fake.add_person(
                        team_id=self.team.pk,
                        person_id=1,
                        uuid=str(person_uuid),
                        distinct_ids=["a", "late-alias"],
                    )
                    added = True
                return original(request, timeout)

            with patch.object(fake, "delete_persons", side_effect=add_alias_before_tombstone):
                assert _delete_specific_persons_via_personhog(self.team.pk, [1], "example-purge") == 1
        receipt = MembershipDeletionReceipt.objects.for_team(self.team.pk).get(
            person_uuid=person_uuid, source_key__startswith="purge:"
        )
        assert self._ids(receipt) == ["a", "late-alias"]

    def test_physical_cleanup_does_not_replace_a_full_manifest_with_partial_remaining_ids(self) -> None:
        person_uuid = uuid4()
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.pk,
                person_id=1,
                uuid=str(person_uuid),
                distinct_ids=["a", "alias"],
            )
            fake.delete_persons(
                DeletePersonsRequest(
                    team_id=self.team.pk,
                    person_uuids=[str(person_uuid)],
                    mode=DeletePersonsMode.DELETE_PERSONS_MODE_TOMBSTONE,
                )
            )
            tombstone = get_person_tombstones(self.team.pk, [person_uuid])[0]
            MembershipDeletionSources.record_tombstones(self.team.pk, [tombstone], required=True)
            receipt = self._receipt(person_uuid)
            partial = type(tombstone)(
                uuid=tombstone.uuid, version=tombstone.version, distinct_ids=tombstone.distinct_ids[:1]
            )
            MembershipDeletionSources.record_tombstones(self.team.pk, [partial], required=True)
        assert self._ids(receipt) == ["a", "alias"]

    def test_team_receipt_commits_with_metadata_removal_without_waiting_for_legacy_ledger(self) -> None:
        team_id = self.team.pk
        with (
            patch("posthog.models.team.util.queue_training_deletion"),
            patch("posthog.clickhouse.cluster.default_client", side_effect=AssertionError("Unexpected discovery")),
        ):
            delete_team_records([team_id])
        assert not Team.objects.filter(id=team_id).exists()
        receipt = MembershipDeletionReceipt.objects.for_team(team_id).get(kind=MembershipDeletionKind.TEAM)
        assert receipt.confirmed_at is not None
        assert receipt.completed_at is None
        assert team_deletion_verified(team_id)

    def test_failed_team_receipt_rolls_back_metadata_removal(self) -> None:
        team_id = self.team.pk
        with (
            patch("posthog.models.team.util.queue_training_deletion"),
            patch.object(MembershipDeletionReceipt, "save", side_effect=RuntimeError("Receipt store unavailable")),
        ):
            with self.assertRaises(RuntimeError):
                delete_team_records([team_id])
        assert Team.objects.filter(id=team_id).exists()
        assert not MembershipDeletionReceipt.objects.for_team(team_id).exists()

    @parameterized.expand([("limited", 1, False), ("exhausted", 2, True)])
    def test_whole_team_purge_confirms_only_when_the_source_batch_is_exhausted(
        self, _name: str, batch_size: int, confirmed: bool
    ) -> None:
        AsyncDeletion.objects.create(team_id=self.team.pk, deletion_type=DeletionType.Team, key=str(self.team.pk))
        with fake_personhog_client() as fake:
            fake.add_person(team_id=self.team.pk, person_id=1, uuid=str(uuid4()), distinct_ids=["a"])
            assert _delete_team_persons_batch_via_personhog(self.team.pk, batch_size, "example-team-purge") == 1
        receipt = MembershipDeletionReceipt.objects.for_team(self.team.pk).get(kind=MembershipDeletionKind.TEAM_PERSONS)
        assert (receipt.confirmed_at is not None) is confirmed
