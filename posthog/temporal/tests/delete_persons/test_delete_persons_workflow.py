import uuid as uuid_lib

import pytest

from asgiref.sync import sync_to_async

from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.temporal.delete_persons.delete_persons_workflow import (
    DeletePersonsActivityInputs,
    PrecleanCohortMembersActivityInputs,
    delete_persons_activity,
    preclean_cohort_members_activity,
)

from products.cohorts.backend.models.cohort import Cohort

pytestmark = pytest.mark.django_db


class TestDeletePersonsActivity:
    async def test_by_ids_resolves_uuids_then_deletes(self, activity_environment):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid=str(uuid_lib.uuid4()), distinct_ids=["d1"])

            deleted, should_continue = await activity_environment.run(
                delete_persons_activity,
                DeletePersonsActivityInputs(team_id=1, person_ids=[10], batch_size=1000),
            )

        assert deleted == 1
        assert should_continue is False
        # by-ids mode resolves ids -> uuids before deleting (cohortpeople via DeletePersons cascade)
        fake.assert_called("get_persons")
        fake.assert_called("delete_persons")

    async def test_by_ids_should_continue_when_more_remain(self, activity_environment):
        with fake_personhog_client() as fake:
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


# transaction=True so the Cohort committed below is visible to the activity's threaded ORM read
# (asyncio.to_thread gets a fresh connection that can't see a rolled-back test transaction).
@pytest.mark.django_db(transaction=True)
class TestPrecleanCohortMembersActivity:
    async def test_clears_team_cohort_memberships(self, activity_environment, ateam):
        cohort = await sync_to_async(Cohort.objects.create)(team=ateam, name="preclean-test")
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
        with fake_personhog_client() as fake:
            await activity_environment.run(
                preclean_cohort_members_activity,
                PrecleanCohortMembersActivityInputs(team_id=ateam.id),
            )

        # With no cohorts to resolve, the bulk delete RPC is never invoked.
        fake.assert_not_called("delete_cohort_members_bulk")
