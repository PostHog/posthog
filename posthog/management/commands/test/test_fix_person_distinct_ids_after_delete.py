import logging
from typing import Dict
from uuid import uuid4

import pytest

from posthog.client import sync_execute
from posthog.management.commands.fix_person_distinct_ids_after_delete import run
from posthog.models.person.person import Person, PersonDistinctId
from posthog.models.person.sql import PERSON_DISTINCT_ID2_TABLE
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.test.base import BaseTest, ClickhouseTestMixin


@pytest.mark.ee
class TestFixPersonDistinctIdsAfterDelete(BaseTest, ClickhouseTestMixin):
    def create_test_person(self, distinct_ids: Dict[str, int]):
        person = Person.objects.create(team_id=self.team.pk, version=0, uuid=uuid4())
        create_person(uuid=str(person.uuid), team_id=person.team.pk, version=person.version)
        for did, version in distinct_ids.items():
            PersonDistinctId.objects.create(team=self.team, person=person, distinct_id=did, version=version)
            create_person_distinct_id(
                team_id=self.team.pk, distinct_id=did, person_id=str(person.uuid), is_deleted=False, version=version
            )
        return person

    def test_live_run(self):
        person1 = self.create_test_person({"did1": 1, "did2": 2, "did3": 3})
        person2 = self.create_test_person({"did5": 11, "did6": 12})
        deleted_uuid = str(uuid4())
        deleted_uuid2 = str(uuid4())
        create_person(uuid=deleted_uuid, team_id=self.team.pk, is_deleted=True, version=5)
        create_person(uuid=deleted_uuid2, team_id=self.team.pk, is_deleted=True, version=5)

        sync_execute(
            f"""
            INSERT INTO {PERSON_DISTINCT_ID2_TABLE} (team_id, distinct_id, person_id, is_deleted, version)
            VALUES
                ({self.team.pk}, 'did1', '{deleted_uuid}', 1, 25)
                ({self.team.pk}, 'did2', '{deleted_uuid2}', 0, 44)
                ({self.team.pk}, 'did6', '{deleted_uuid2}', 1, 50)
            """
        )

        options = {"live_run": True, "team_id": self.team.pk, "new_version": 2500}
        run(options)

        did1 = PersonDistinctId.objects.get(distinct_id="did1")
        did2 = PersonDistinctId.objects.get(distinct_id="did2")
        did3 = PersonDistinctId.objects.get(distinct_id="did3")
        did5 = PersonDistinctId.objects.get(distinct_id="did5")
        did6 = PersonDistinctId.objects.get(distinct_id="did6")

        self.assertEqual(did1.version, 2500)
        self.assertEqual(did1.person.pk, person1.pk)
        self.assertEqual(did2.version, 2500)
        self.assertEqual(did2.person.pk, person1.pk)
        self.assertEqual(did3.version, 3)
        self.assertEqual(did3.person.pk, person1.pk)
        self.assertEqual(did5.version, 11)
        self.assertEqual(did5.person.pk, person2.pk)
        self.assertEqual(did6.version, 2500)
        self.assertEqual(did6.person.pk, person2.pk)

        sync_execute(f"OPTIMIZE TABLE {PERSON_DISTINCT_ID2_TABLE}")
        distinct_ids_after = sync_execute(
            f"select distinct_id, person_id, version from {PERSON_DISTINCT_ID2_TABLE} ORDER BY distinct_id"
        )
        self.assertEqual(
            distinct_ids_after,
            [
                ("did1", person1.uuid, 2500),
                ("did2", person1.uuid, 2500),
                ("did3", person1.uuid, 3),
                ("did5", person2.uuid, 11),
                ("did6", person2.uuid, 2500),
            ],
        )


@pytest.fixture(autouse=True)
def set_log_level(caplog):
    caplog.set_level(logging.INFO)
