import uuid as uuid_lib

import pytest

from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.temporal.delete_persons.delete_persons_workflow import DeletePersonsActivityInputs, delete_persons_activity

pytestmark = pytest.mark.django_db


class TestDeletePersonsActivity:
    async def test_by_ids_resolves_uuids_then_deletes(self, activity_environment):
        with fake_personhog_client(gate_enabled=True) as fake:
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
        with fake_personhog_client(gate_enabled=True) as fake:
            for pid in (1, 2, 3):
                fake.add_person(team_id=1, person_id=pid, uuid=str(uuid_lib.uuid4()), distinct_ids=[f"d{pid}"])

            deleted, should_continue = await activity_environment.run(
                delete_persons_activity,
                DeletePersonsActivityInputs(team_id=1, person_ids=[1, 2, 3], batch_number=0, batch_size=2),
            )

        assert deleted == 2
        assert should_continue is True  # one of three ids is left for the next batch

    async def test_whole_team_uses_batch_for_team_rpc(self, activity_environment):
        with fake_personhog_client(gate_enabled=True) as fake:
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
