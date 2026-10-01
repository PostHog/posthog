"""Tests for the undelete-repair version writes via personhog RPC.

Covers the two personhog RPC writes in the repair flow:
- _update_distinct_id_in_postgres → SetPersonDistinctIdVersionFloor
- _set_person_version_floor (used by _reset_person_in_clickhouse) → SetPersonVersionFloor
"""

from uuid import uuid4

from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person import Person, deletion
from posthog.models.person.deletion import (
    _set_person_version_floor,
    _update_distinct_id_in_postgres,
    _updated_distinct_ids,
)
from posthog.personhog_client.fake_client import fake_personhog_client


class TestUpdateDistinctIdInPostgresRPC(SimpleTestCase):
    def test_personhog_path_returns_converted_person(self):
        person_uuid = str(uuid4())
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid=person_uuid,
                properties={"email": "test@example.com"},
                distinct_ids=["did-1"],
            )

            result = _update_distinct_id_in_postgres("did-1", 100, team_id=1)

            calls = fake.assert_called("set_person_distinct_id_version_floor")
            assert calls[0].request.team_id == 1
            assert calls[0].request.distinct_id == "did-1"
            assert calls[0].request.min_version == 100

        assert result is not None
        assert str(result.uuid) == person_uuid
        assert result.properties == {"email": "test@example.com"}

    def test_personhog_returns_none_when_distinct_id_absent(self):
        with fake_personhog_client():
            # Fake not seeded → no person for this distinct_id.
            result = _update_distinct_id_in_postgres("never-used", 100, team_id=1)

        assert result is None


class TestSetPersonVersionFloorRPC(SimpleTestCase):
    def test_personhog_path_calls_rpc_with_floor(self):
        with fake_personhog_client() as fake:
            _set_person_version_floor(1, 42, 500)

            calls = fake.assert_called("set_person_version_floor")
            assert calls[0].request.team_id == 1
            assert calls[0].request.person_id == 42
            assert calls[0].request.min_version == 500


class TestUpdatedDistinctIdsSkipsDeleted(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_live_person", "none", False),
            ("distinct_id_moved_to_another_person", "other", False),
            ("replica_lags_a_delete_on_the_primary", "same", True),
        ]
    )
    def test_leaves_the_distinct_id_unpublished(self, _name: str, replica_owner: str, deleted: bool) -> None:
        owner_uuid = uuid4()
        live_person = {
            "none": None,
            "other": Person(uuid=uuid4(), team_id=1),
            "same": Person(uuid=owner_uuid, team_id=1),
        }[replica_owner]
        with (
            fake_personhog_client() as fake,
            mock.patch.object(deletion, "get_person_by_distinct_id", return_value=live_person),
            mock.patch.object(deletion, "create_person_distinct_id") as publish_distinct_id,
            mock.patch.object(deletion, "create_person") as publish_person,
        ):
            fake.add_person(
                team_id=1, person_id=42, uuid=str(owner_uuid), version=3, distinct_ids=["did-1"], is_deleted=deleted
            )

            _updated_distinct_ids(1, [("did-1", 105)])

            fake.assert_not_called("set_person_version_floor")

        publish_distinct_id.assert_not_called()
        publish_person.assert_not_called()
