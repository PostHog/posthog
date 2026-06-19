"""Tests for the undelete-repair version writes via personhog RPC.

Covers routing/fallback for the two persons-DB writes in the repair flow:
- _update_distinct_id_in_postgres → SetPersonDistinctIdVersionFloor
- _set_person_version_floor (used by _reset_person_in_clickhouse) → SetPersonVersionFloor
"""

from uuid import uuid4

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person.deletion import _set_person_version_floor, _update_distinct_id_in_postgres
from posthog.personhog_client.fake_client import fake_personhog_client


class TestUpdateDistinctIdInPostgresRouting(SimpleTestCase):
    @parameterized.expand(
        [
            ("personhog_success", True, None),
            ("personhog_error_falls_back_to_orm", True, RuntimeError("grpc timeout")),
            ("gate_off_uses_orm_directly", False, None),
        ]
    )
    @patch("posthog.models.person.deletion._set_distinct_id_version_floor_via_orm")
    def test_routing(self, _name, gate_on, grpc_exception, mock_orm):
        mock_orm.return_value = None
        with fake_personhog_client(gate_enabled=gate_on) as fake:
            if grpc_exception is not None:
                fake.set_person_distinct_id_version_floor = MagicMock(side_effect=grpc_exception)

            _update_distinct_id_in_postgres("did-1", 100, team_id=1)

        if gate_on and grpc_exception is None:
            mock_orm.assert_not_called()
        else:
            mock_orm.assert_called_once_with(1, "did-1", 100)

    @patch("posthog.models.person.deletion._set_distinct_id_version_floor_via_orm")
    def test_personhog_path_returns_converted_person(self, mock_orm):
        person_uuid = str(uuid4())
        with fake_personhog_client(gate_enabled=True) as fake:
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
        mock_orm.assert_not_called()

    @patch("posthog.models.person.deletion._set_distinct_id_version_floor_via_orm")
    def test_personhog_returns_none_when_distinct_id_absent(self, mock_orm):
        with fake_personhog_client(gate_enabled=True):
            # Fake not seeded → no person for this distinct_id.
            result = _update_distinct_id_in_postgres("never-used", 100, team_id=1)

        assert result is None
        mock_orm.assert_not_called()


class TestSetPersonVersionFloorRouting(SimpleTestCase):
    @parameterized.expand(
        [
            ("personhog_success", True, None),
            ("personhog_error_falls_back_to_orm", True, RuntimeError("grpc timeout")),
            ("gate_off_uses_orm_directly", False, None),
        ]
    )
    @patch("posthog.models.person.deletion._set_person_version_floor_via_orm")
    def test_routing(self, _name, gate_on, grpc_exception, mock_orm):
        with fake_personhog_client(gate_enabled=gate_on) as fake:
            if grpc_exception is not None:
                fake.set_person_version_floor = MagicMock(side_effect=grpc_exception)

            _set_person_version_floor(1, 42, 500, "default")

        if gate_on and grpc_exception is None:
            mock_orm.assert_not_called()
        else:
            mock_orm.assert_called_once_with(42, 500, "default")

    @patch("posthog.models.person.deletion._set_person_version_floor_via_orm")
    def test_personhog_path_calls_rpc_with_floor(self, mock_orm):
        with fake_personhog_client(gate_enabled=True) as fake:
            _set_person_version_floor(1, 42, 500, "default")

            calls = fake.assert_called("set_person_version_floor")
            assert calls[0].request.team_id == 1
            assert calls[0].request.person_id == 42
            assert calls[0].request.min_version == 500

        mock_orm.assert_not_called()
