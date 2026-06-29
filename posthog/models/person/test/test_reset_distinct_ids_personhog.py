"""Tests for the undelete-repair version writes via personhog RPC.

Covers the two personhog RPC writes in the repair flow:
- _update_distinct_id_in_postgres → SetPersonDistinctIdVersionFloor
- _set_person_version_floor (used by _reset_person_in_clickhouse) → SetPersonVersionFloor
"""

from uuid import uuid4

from django.test import SimpleTestCase

from posthog.models.person.deletion import _set_person_version_floor, _update_distinct_id_in_postgres
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
