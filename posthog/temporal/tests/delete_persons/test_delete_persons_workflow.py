import uuid as uuid_lib

import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from temporalio.exceptions import ApplicationError

from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person.bulk_delete import PersonTombstoneFailed
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.proto import DeletePersonsMode
from posthog.temporal.delete_persons.delete_persons_workflow import (
    DeletePersonsActivityInputs,
    PrecleanCohortMembersActivityInputs,
    delete_persons_activity,
    preclean_cohort_members_activity,
)

from products.cohorts.backend.models.cohort import Cohort

pytestmark = pytest.mark.django_db


def _no_publish():
    return patch("posthog.models.person.util.publish_person_tombstone", return_value=[])


class TestDeletePersonsActivity:
    async def test_by_ids_tombstones_and_publishes_at_the_postgres_version(self, activity_environment):
        person_uuid = str(uuid_lib.uuid4())
        with fake_personhog_client() as fake, _no_publish() as publish:
            fake.add_person(team_id=1, person_id=10, uuid=person_uuid, version=3, distinct_ids=["d1"])

            deleted, should_continue = await activity_environment.run(
                delete_persons_activity,
                DeletePersonsActivityInputs(team_id=1, person_ids=[10], batch_size=1000),
            )

        assert deleted == 1
        assert should_continue is False
        modes = {call.request.mode for call in fake.calls if call.method == "delete_persons"}
        assert modes == {DeletePersonsMode.DELETE_PERSONS_MODE_TOMBSTONE}
        stored = fake._persons_by_uuid[(1, person_uuid)]
        assert (stored.is_deleted, stored.version) == (True, 4)
        publish.assert_called_once()
        tombstone = publish.call_args.args[1]
        assert (str(tombstone.uuid), tombstone.version) == (person_uuid, 4)
        assert [(d.id, d.version) for d in tombstone.distinct_ids] == [("d1", 1)]
        assert fake.tombstone_queue == {}

    async def test_by_ids_pages_distinct_ids_and_bounds_each_tombstone_rpc(self, activity_environment):
        with (
            fake_personhog_client() as fake,
            _no_publish(),
            patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_ID_PAGE_SIZE", 2),
            patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_IDS_PER_BATCH", 3),
        ):
            for pid in (10, 11):
                fake.add_person(
                    team_id=1,
                    person_id=pid,
                    uuid=str(uuid_lib.uuid4()),
                    distinct_ids=[f"{pid}-a", f"{pid}-b", f"{pid}-c"],
                )

            deleted, _ = await activity_environment.run(
                delete_persons_activity,
                DeletePersonsActivityInputs(team_id=1, person_ids=[10, 11], batch_size=1000),
            )

        assert deleted == 2
        assert {call.method for call in fake.calls} & {"get_distinct_ids_for_persons"} == set()
        page_limits = [call.request.limit for call in fake.calls if call.method == "get_distinct_ids_for_person"]
        assert page_limits == [2, 2, 2, 2]
        tombstone_batches = [len(call.request.person_uuids) for call in fake.calls if call.method == "delete_persons"]
        assert tombstone_batches == [1, 1]

    async def test_by_ids_raises_and_leaves_persons_live_when_the_postgres_tombstone_fails(self, activity_environment):
        person_uuid = str(uuid_lib.uuid4())
        with fake_personhog_client() as fake, _no_publish() as publish:
            fake.add_person(team_id=1, person_id=10, uuid=person_uuid, distinct_ids=["d1"])

            with (
                patch.object(fake, "delete_persons", side_effect=RuntimeError("replica down")),
                pytest.raises(PersonTombstoneFailed),
            ):
                await activity_environment.run(
                    delete_persons_activity,
                    DeletePersonsActivityInputs(team_id=1, person_ids=[10], batch_size=1000),
                )

        assert fake._persons_by_uuid[(1, person_uuid)].is_deleted is False
        publish.assert_not_called()

    async def test_by_ids_should_continue_when_more_remain(self, activity_environment):
        with fake_personhog_client() as fake, _no_publish():
            for pid in (1, 2, 3):
                fake.add_person(team_id=1, person_id=pid, uuid=str(uuid_lib.uuid4()), distinct_ids=[f"d{pid}"])

            deleted, should_continue = await activity_environment.run(
                delete_persons_activity,
                DeletePersonsActivityInputs(team_id=1, person_ids=[1, 2, 3], batch_number=0, batch_size=2),
            )

        assert deleted == 2
        assert should_continue is True  # one of three ids is left for the next batch

    async def test_whole_team_uses_batch_for_team_rpc(self, activity_environment):
        with fake_personhog_client() as fake:
            for pid in (1, 2):
                fake.add_person(team_id=1, person_id=pid, uuid=str(uuid_lib.uuid4()))

            deleted, should_continue = await activity_environment.run(
                delete_persons_activity,
                DeletePersonsActivityInputs(team_id=1, person_ids=[], batch_size=1),
            )

        assert deleted == 1
        assert should_continue is True  # deleted == batch_size, so a batch may still remain
        # whole-team mode never resolves ids; it deletes straight through the team-batch RPC
        fake.assert_called("delete_persons_batch_for_team")


def _mark_team_deleted(team_id: int) -> None:
    AsyncDeletion.objects.create(deletion_type=DeletionType.Team, team_id=team_id, key=str(team_id))


# transaction=True so the rows committed below are visible to the activity's threaded ORM read
# (asyncio.to_thread gets a fresh connection that can't see a rolled-back test transaction).
@pytest.mark.django_db(transaction=True)
class TestWholeTeamModeRefusesLiveTeams:
    @pytest.mark.parametrize("whole_team_activity", ["preclean", "delete"])
    async def test_refuses_a_live_team_before_deleting_anything(self, activity_environment, ateam, whole_team_activity):
        cohort = await sync_to_async(Cohort.objects.create)(team=ateam, name="live-team")
        with fake_personhog_client() as fake:
            fake.add_person(team_id=ateam.id, person_id=1, uuid=str(uuid_lib.uuid4()))
            fake.add_cohort_membership(person_id=1, cohort_id=cohort.id)

            with pytest.raises(ApplicationError) as refused:
                if whole_team_activity == "preclean":
                    await activity_environment.run(
                        preclean_cohort_members_activity, PrecleanCohortMembersActivityInputs(team_id=ateam.id)
                    )
                else:
                    await activity_environment.run(
                        delete_persons_activity, DeletePersonsActivityInputs(team_id=ateam.id, batch_size=10)
                    )

        assert refused.value.non_retryable
        fake.assert_not_called("delete_cohort_members_bulk")
        fake.assert_not_called("delete_persons_batch_for_team")

    async def test_deletes_once_the_team_is_queued_for_clickhouse_deletion(self, activity_environment, ateam):
        await sync_to_async(_mark_team_deleted)(ateam.id)
        with fake_personhog_client() as fake:
            fake.add_person(team_id=ateam.id, person_id=1, uuid=str(uuid_lib.uuid4()))

            deleted, _ = await activity_environment.run(
                delete_persons_activity, DeletePersonsActivityInputs(team_id=ateam.id, batch_size=10)
            )

        assert deleted == 1


@pytest.mark.django_db(transaction=True)
class TestPrecleanCohortMembersActivity:
    async def test_clears_team_cohort_memberships(self, activity_environment, ateam):
        cohort = await sync_to_async(Cohort.objects.create)(team=ateam, name="preclean-test")
        await sync_to_async(_mark_team_deleted)(ateam.id)
        with fake_personhog_client() as fake:
            fake.add_cohort_membership(person_id=5, cohort_id=cohort.id)

            await activity_environment.run(
                preclean_cohort_members_activity,
                PrecleanCohortMembersActivityInputs(team_id=ateam.id),
            )

        # Whole-team preclean resolves the team's cohorts and clears their members via the bulk RPC.
        fake.assert_called("delete_cohort_members_bulk")
        assert (cohort.id, 5) not in fake._cohort_members

    async def test_noop_when_team_has_no_cohorts(self, activity_environment, ateam):
        await sync_to_async(_mark_team_deleted)(ateam.id)
        with fake_personhog_client() as fake:
            await activity_environment.run(
                preclean_cohort_members_activity,
                PrecleanCohortMembersActivityInputs(team_id=ateam.id),
            )

        # With no cohorts to resolve, the bulk delete RPC is never invoked.
        fake.assert_not_called("delete_cohort_members_bulk")
