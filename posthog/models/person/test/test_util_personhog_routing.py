from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized, parameterized_class

from posthog.models.person.util import (
    _fetch_person_by_distinct_id_via_personhog,
    _fetch_person_by_id_via_personhog,
    _fetch_person_by_uuid_via_personhog,
    _fetch_persons_by_distinct_ids_via_personhog,
    _fetch_persons_by_uuids_via_personhog,
    _personhog_routed,
    _validate_uuids_via_personhog,
    get_person_by_distinct_id,
    get_person_by_id,
    get_person_by_pk_or_uuid,
    get_person_by_uuid,
    get_persons_by_distinct_ids,
    get_persons_by_uuids,
    get_persons_mapped_by_distinct_id,
    validate_person_uuids_exist,
)
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.test_helpers import PersonhogTestMixin

# ── Routing tests ────────────────────────────────────────────────────
# These use mocks to test gate/fallback/metrics logic in _personhog_routed.


class TestGetPersonByUuidRouting(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "personhog_success",
                True,
                "mock_person",
                None,
                "personhog",
            ),
            (
                "personhog_returns_none",
                True,
                None,
                None,
                "personhog",
            ),
            (
                "personhog_failure_falls_back_to_orm",
                True,
                None,
                RuntimeError("grpc timeout"),
                "django_orm",
            ),
            (
                "gate_off_uses_orm_directly",
                False,
                None,
                None,
                "django_orm",
            ),
        ]
    )
    @patch("posthog.models.person.util.Person.objects")
    @patch("posthog.models.person.util._fetch_person_by_uuid_via_personhog")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_routing(
        self,
        _name,
        gate_on,
        personhog_data,
        grpc_exception,
        expected_source,
        mock_errors_counter,
        mock_routing_counter,
        mock_use_personhog,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_use_personhog.return_value = gate_on

        if grpc_exception is not None:
            mock_fetch_personhog.side_effect = grpc_exception
        else:
            mock_fetch_personhog.return_value = personhog_data

        mock_qs = MagicMock()
        mock_qs.first.return_value = MagicMock()
        mock_objects.db_manager.return_value.filter.return_value = mock_qs

        result = get_person_by_uuid(1, "some-uuid")

        if gate_on and grpc_exception is None:
            assert result == personhog_data
            mock_objects.db_manager.assert_not_called()
        else:
            mock_objects.db_manager.assert_called()

        mock_routing_counter.labels.assert_called_with(
            operation="get_person_by_uuid", source=expected_source, client_name="posthog-django"
        )

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()


class TestGetPersonByDistinctIdRouting(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "personhog_success",
                True,
                "mock_person",
                None,
                "personhog",
            ),
            (
                "personhog_returns_none",
                True,
                None,
                None,
                "personhog",
            ),
            (
                "personhog_failure_falls_back_to_orm",
                True,
                None,
                RuntimeError("grpc timeout"),
                "django_orm",
            ),
            (
                "gate_off_uses_orm_directly",
                False,
                None,
                None,
                "django_orm",
            ),
        ]
    )
    @patch("posthog.models.person.util.Person.objects")
    @patch("posthog.models.person.util._fetch_person_by_distinct_id_via_personhog")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_routing(
        self,
        _name,
        gate_on,
        personhog_data,
        grpc_exception,
        expected_source,
        mock_errors_counter,
        mock_routing_counter,
        mock_use_personhog,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_use_personhog.return_value = gate_on

        if grpc_exception is not None:
            mock_fetch_personhog.side_effect = grpc_exception
        else:
            mock_fetch_personhog.return_value = personhog_data

        mock_qs = MagicMock()
        mock_qs.first.return_value = MagicMock()
        mock_objects.db_manager.return_value.filter.return_value = mock_qs

        result = get_person_by_distinct_id(1, "some-distinct-id")

        if gate_on and grpc_exception is None:
            assert result == personhog_data
            mock_objects.db_manager.assert_not_called()
        else:
            mock_objects.db_manager.assert_called()

        mock_routing_counter.labels.assert_called_with(
            operation="get_person_by_distinct_id", source=expected_source, client_name="posthog-django"
        )

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()


class TestGetPersonByIdRouting(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "personhog_success",
                True,
                "mock_person",
                None,
                "personhog",
            ),
            (
                "personhog_returns_none",
                True,
                None,
                None,
                "personhog",
            ),
            (
                "personhog_failure_falls_back_to_orm",
                True,
                None,
                RuntimeError("grpc timeout"),
                "django_orm",
            ),
            (
                "gate_off_uses_orm_directly",
                False,
                None,
                None,
                "django_orm",
            ),
        ]
    )
    @patch("posthog.models.person.util.Person.objects")
    @patch("posthog.models.person.util._fetch_person_by_id_via_personhog")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_routing(
        self,
        _name,
        gate_on,
        personhog_data,
        grpc_exception,
        expected_source,
        mock_errors_counter,
        mock_routing_counter,
        mock_use_personhog,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_use_personhog.return_value = gate_on

        if grpc_exception is not None:
            mock_fetch_personhog.side_effect = grpc_exception
        else:
            mock_fetch_personhog.return_value = personhog_data

        mock_qs = MagicMock()
        mock_qs.first.return_value = MagicMock()
        mock_objects.db_manager.return_value.filter.return_value = mock_qs

        result = get_person_by_id(1, 42)

        if gate_on and grpc_exception is None:
            assert result == personhog_data
            mock_objects.db_manager.assert_not_called()
        else:
            mock_objects.db_manager.assert_called()

        mock_routing_counter.labels.assert_called_with(
            operation="get_person_by_id", source=expected_source, client_name="posthog-django"
        )

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()


class TestGetPersonsByUuidsRouting(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "personhog_success",
                True,
                ["person_a", "person_b"],
                None,
                "personhog",
            ),
            (
                "personhog_failure_falls_back_to_orm",
                True,
                None,
                RuntimeError("grpc timeout"),
                "django_orm",
            ),
            (
                "gate_off_uses_orm_directly",
                False,
                None,
                None,
                "django_orm",
            ),
        ]
    )
    @patch("posthog.models.person.util.Person.objects")
    @patch("posthog.models.person.util._fetch_persons_by_uuids_via_personhog")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_routing(
        self,
        _name,
        gate_on,
        personhog_data,
        grpc_exception,
        expected_source,
        mock_errors_counter,
        mock_routing_counter,
        mock_use_personhog,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_use_personhog.return_value = gate_on

        if personhog_data is not None:
            mock_fetch_personhog.return_value = personhog_data
        elif grpc_exception is not None:
            mock_fetch_personhog.side_effect = grpc_exception

        mock_qs = MagicMock()
        mock_objects.db_manager.return_value.filter.return_value = mock_qs

        team_id = 1
        uuids = ["uuid-1", "uuid-2"]

        result = get_persons_by_uuids(team_id, uuids)

        if personhog_data is not None and gate_on:
            assert result == personhog_data
            mock_fetch_personhog.assert_called_once_with(team_id, uuids)
            mock_objects.db_manager.assert_not_called()
        else:
            assert result == mock_qs
            mock_objects.db_manager.return_value.filter.assert_called_with(team_id=team_id, uuid__in=uuids)

        mock_routing_counter.labels.assert_called_with(
            operation="get_persons_by_uuids", source=expected_source, client_name="posthog-django"
        )

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()


class TestGetPersonsByDistinctIdsRouting(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "personhog_success",
                True,
                None,
                "personhog",
            ),
            (
                "personhog_failure_falls_back_to_orm",
                True,
                RuntimeError("grpc timeout"),
                "django_orm",
            ),
            (
                "gate_off_uses_orm_directly",
                False,
                None,
                "django_orm",
            ),
        ]
    )
    @patch("posthog.models.person.util._fetch_persons_by_distinct_ids_via_personhog")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_routing(
        self,
        _name,
        gate_on,
        grpc_exception,
        expected_source,
        mock_errors_counter,
        mock_routing_counter,
        mock_use_personhog,
        mock_fetch_personhog,
    ):
        mock_use_personhog.return_value = gate_on

        personhog_persons = [MagicMock(), MagicMock()]
        if grpc_exception is not None:
            mock_fetch_personhog.side_effect = grpc_exception
        else:
            mock_fetch_personhog.return_value = personhog_persons

        team_id = 1
        distinct_ids = ["did-1", "did-2"]

        if gate_on and grpc_exception is None:
            result = get_persons_by_distinct_ids(team_id, distinct_ids)
            assert result == personhog_persons
        else:
            with (
                patch("posthog.models.person.util.Person.objects") as mock_person_objects,
                patch("posthog.models.person.util.PersonDistinctId.objects"),
                patch("posthog.models.person.util.Prefetch"),
            ):
                mock_qs = MagicMock()
                mock_qs.__iter__ = MagicMock(return_value=iter([]))
                mock_person_objects.db_manager.return_value.filter.return_value.prefetch_related.return_value = mock_qs

                result = get_persons_by_distinct_ids(team_id, distinct_ids)
                assert result == []

        mock_routing_counter.labels.assert_called_with(
            operation="get_persons_by_distinct_ids", source=expected_source, client_name="posthog-django"
        )

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()


class TestGetPersonsMappedByDistinctIdRouting(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "personhog_success",
                True,
                None,
                "personhog",
            ),
            (
                "personhog_failure_falls_back_to_orm",
                True,
                RuntimeError("grpc timeout"),
                "django_orm",
            ),
            (
                "gate_off_uses_orm_directly",
                False,
                None,
                "django_orm",
            ),
        ]
    )
    @patch("posthog.models.person.util.PersonDistinctId.objects")
    @patch("posthog.personhog_client.client.get_personhog_client")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_routing(
        self,
        _name,
        gate_on,
        grpc_exception,
        expected_source,
        mock_errors_counter,
        mock_routing_counter,
        mock_use_personhog,
        mock_get_client,
        mock_pdi_objects,
    ):
        mock_use_personhog.return_value = gate_on

        mock_client = MagicMock()
        if grpc_exception is not None:
            mock_client.get_persons_by_distinct_ids_in_team.side_effect = grpc_exception
        mock_get_client.return_value = mock_client

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([]))
        mock_pdi_objects.db_manager.return_value.filter.return_value.select_related.return_value = mock_qs

        get_persons_mapped_by_distinct_id(1, ["did-1"])

        if gate_on and grpc_exception is None:
            mock_pdi_objects.db_manager.assert_not_called()
        else:
            mock_pdi_objects.db_manager.assert_called()

        mock_routing_counter.labels.assert_called_with(
            operation="get_persons_mapped_by_distinct_id", source=expected_source, client_name="posthog-django"
        )

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()


class TestValidatePersonUuidsExistRouting(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "personhog_success",
                True,
                ["uuid-1", "uuid-2"],
                None,
                "personhog",
            ),
            (
                "personhog_failure_falls_back_to_orm",
                True,
                None,
                RuntimeError("grpc timeout"),
                "django_orm",
            ),
            (
                "gate_off_uses_orm_directly",
                False,
                None,
                None,
                "django_orm",
            ),
        ]
    )
    @patch("posthog.models.person.util.Person.objects")
    @patch("posthog.models.person.util._validate_uuids_via_personhog")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_routing(
        self,
        _name,
        gate_on,
        personhog_data,
        grpc_exception,
        expected_source,
        mock_errors_counter,
        mock_routing_counter,
        mock_use_personhog,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_use_personhog.return_value = gate_on

        if grpc_exception is not None:
            mock_fetch_personhog.side_effect = grpc_exception
        else:
            mock_fetch_personhog.return_value = personhog_data

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([]))
        mock_objects.db_manager.return_value.filter.return_value.values_list.return_value = mock_qs

        result = validate_person_uuids_exist(1, ["uuid-1", "uuid-2"])

        if gate_on and grpc_exception is None:
            assert result == personhog_data
            mock_objects.db_manager.assert_not_called()
        else:
            mock_objects.db_manager.assert_called()

        mock_routing_counter.labels.assert_called_with(
            operation="validate_person_uuids_exist", source=expected_source, client_name="posthog-django"
        )

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()


# ── Personhog internal logic tests ──────────────────────────────────
# These use the fake personhog client to exercise the real proto/converter pipeline.


class TestFetchPersonByUuidViaPersonhog(SimpleTestCase):
    def test_returns_person_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                properties={"email": "test@example.com"},
                is_identified=True,
                created_at=1700000000000,
                distinct_ids=["did-1", "did-2"],
            )

            result = _fetch_person_by_uuid_via_personhog(team_id=1, uuid="550e8400-e29b-41d4-a716-446655440000")

            assert result is not None
            assert result.id == 42
            assert result.properties == {"email": "test@example.com"}
            assert result.distinct_ids == ["did-1", "did-2"]
            fake.assert_called("get_person_by_uuid")
            fake.assert_called("get_distinct_ids_for_person")

    def test_returns_none_when_person_not_found(self):
        with fake_personhog_client() as fake:
            result = _fetch_person_by_uuid_via_personhog(team_id=1, uuid="nonexistent")

            assert result is None
            fake.assert_called("get_person_by_uuid")
            fake.assert_not_called("get_distinct_ids_for_person")

    def test_returns_none_on_team_mismatch(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                distinct_ids=["did-1"],
            )

            result = _fetch_person_by_uuid_via_personhog(team_id=1, uuid="550e8400-e29b-41d4-a716-446655440000")

            assert result is None
            fake.assert_not_called("get_distinct_ids_for_person")


class TestFetchPersonByDistinctIdViaPersonhog(SimpleTestCase):
    def test_returns_person_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                properties={"email": "test@example.com"},
                is_identified=True,
                created_at=1700000000000,
                distinct_ids=["did-1", "did-2"],
            )

            result = _fetch_person_by_distinct_id_via_personhog(team_id=1, distinct_id="did-1")

            assert result is not None
            assert result.id == 42
            assert result.distinct_ids == ["did-1", "did-2"]
            fake.assert_called("get_person_by_distinct_id")

    def test_returns_none_when_person_not_found(self):
        with fake_personhog_client() as fake:
            result = _fetch_person_by_distinct_id_via_personhog(team_id=1, distinct_id="nonexistent")

            assert result is None
            fake.assert_not_called("get_distinct_ids_for_person")

    def test_returns_none_on_team_mismatch(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                distinct_ids=["did-1"],
            )

            result = _fetch_person_by_distinct_id_via_personhog(team_id=1, distinct_id="did-1")

            assert result is None
            fake.assert_not_called("get_distinct_ids_for_person")


class TestFetchPersonByIdViaPersonhog(SimpleTestCase):
    def test_returns_person_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                properties={"email": "test@example.com"},
                is_identified=True,
                created_at=1700000000000,
                distinct_ids=["did-1", "did-2"],
            )

            result = _fetch_person_by_id_via_personhog(team_id=1, person_id=42)

            assert result is not None
            assert result.id == 42
            assert result.properties == {"email": "test@example.com"}
            assert result.distinct_ids == ["did-1", "did-2"]
            fake.assert_called("get_person")
            fake.assert_called("get_distinct_ids_for_person")

    def test_returns_none_when_person_not_found(self):
        with fake_personhog_client() as fake:
            result = _fetch_person_by_id_via_personhog(team_id=1, person_id=999)

            assert result is None
            fake.assert_called("get_person")
            fake.assert_not_called("get_distinct_ids_for_person")

    def test_returns_none_on_team_mismatch(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                distinct_ids=["did-1"],
            )

            result = _fetch_person_by_id_via_personhog(team_id=1, person_id=42)

            assert result is None
            fake.assert_not_called("get_distinct_ids_for_person")


class TestFetchPersonsByDistinctIdsViaPersonhog(SimpleTestCase):
    def test_returns_persons_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                properties={"email": "real@example.com"},
                is_identified=True,
                created_at=1700000000000,
                distinct_ids=["did-1", "did-2"],
            )

            result = _fetch_persons_by_distinct_ids_via_personhog(team_id=1, distinct_ids=["did-1"])

            assert len(result) == 1
            assert result[0].id == 42
            assert result[0].properties == {"email": "real@example.com"}
            assert result[0].distinct_ids == ["did-1", "did-2"]
            fake.assert_called("get_persons_by_distinct_ids_in_team")
            fake.assert_called("get_distinct_ids_for_persons")

    def test_no_results_for_missing_distinct_ids(self):
        with fake_personhog_client() as fake:
            result = _fetch_persons_by_distinct_ids_via_personhog(team_id=1, distinct_ids=["nonexistent"])

            assert result == []
            fake.assert_called("get_persons_by_distinct_ids_in_team")
            fake.assert_not_called("get_distinct_ids_for_persons")

    def test_cross_team_isolation(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["did-1"]
            )

            result = _fetch_persons_by_distinct_ids_via_personhog(team_id=1, distinct_ids=["did-1"])

            assert result == []

    def test_deduplicates_persons_with_multiple_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["did-1", "did-2"]
            )

            result = _fetch_persons_by_distinct_ids_via_personhog(team_id=1, distinct_ids=["did-1", "did-2"])

            assert len(result) == 1

    def test_respects_distinct_id_limit(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440042",
                distinct_ids=["did-1", "did-2", "did-3"],
            )

            result = _fetch_persons_by_distinct_ids_via_personhog(
                team_id=1, distinct_ids=["did-1"], distinct_id_limit=1
            )

            assert len(result) == 1
            assert len(result[0].distinct_ids) == 1


class TestFetchPersonsByUuidsViaPersonhog(SimpleTestCase):
    def test_returns_persons_with_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=1,
                uuid="550e8400-e29b-41d4-a716-446655440001",
                properties={"name": "Alice"},
                distinct_ids=["alice-did"],
            )
            fake.add_person(
                team_id=1,
                person_id=2,
                uuid="550e8400-e29b-41d4-a716-446655440002",
                properties={"name": "Bob"},
                distinct_ids=["bob-did"],
            )

            result = _fetch_persons_by_uuids_via_personhog(
                team_id=1,
                uuids=["550e8400-e29b-41d4-a716-446655440001", "550e8400-e29b-41d4-a716-446655440002"],
            )

            assert len(result) == 2
            assert result[0].properties == {"name": "Alice"}
            assert result[0].distinct_ids == ["alice-did"]
            assert result[1].properties == {"name": "Bob"}
            assert result[1].distinct_ids == ["bob-did"]
            fake.assert_called("get_persons_by_uuids")
            fake.assert_called("get_distinct_ids_for_persons")

    def test_returns_empty_for_missing_uuids(self):
        with fake_personhog_client() as fake:
            result = _fetch_persons_by_uuids_via_personhog(team_id=1, uuids=["nonexistent"])

            assert result == []
            fake.assert_called("get_persons_by_uuids")
            fake.assert_not_called("get_distinct_ids_for_persons")

    def test_cross_team_isolation(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["did-1"]
            )

            result = _fetch_persons_by_uuids_via_personhog(team_id=1, uuids=["550e8400-e29b-41d4-a716-446655440042"])

            assert result == []

    def test_person_with_no_distinct_ids_gets_empty_list(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042")

            result = _fetch_persons_by_uuids_via_personhog(team_id=1, uuids=["550e8400-e29b-41d4-a716-446655440042"])

            assert len(result) == 1
            assert result[0].distinct_ids == []


class TestValidateUuidsViaPersonhog(SimpleTestCase):
    def test_returns_matching_uuids(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])
            fake.add_person(team_id=1, person_id=2, uuid="uuid-2", distinct_ids=["d2"])

            result = _validate_uuids_via_personhog(team_id=1, uuids=["uuid-1", "uuid-2", "uuid-missing"])

            assert set(result) == {"uuid-1", "uuid-2"}
            fake.assert_called("get_persons_by_uuids")

    def test_filters_out_wrong_team(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])
            fake.add_person(team_id=999, person_id=2, uuid="uuid-2", distinct_ids=["d2"])

            result = _validate_uuids_via_personhog(team_id=1, uuids=["uuid-1", "uuid-2"])

            assert result == ["uuid-1"]

    def test_returns_empty_when_no_matches(self):
        with fake_personhog_client() as fake:
            result = _validate_uuids_via_personhog(team_id=1, uuids=["nonexistent"])

            assert result == []
            fake.assert_called("get_persons_by_uuids")


class TestPersonsMappedByDistinctIdViaPersonhog(SimpleTestCase):
    def test_returns_mapping(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                properties={"email": "test@example.com"},
                distinct_ids=["did-1", "did-2"],
            )

            result = get_persons_mapped_by_distinct_id(1, ["did-1"])

            assert "did-1" in result
            assert result["did-1"].id == 42
            assert result["did-1"].distinct_ids == ["did-1"]
            fake.assert_called("get_persons_by_distinct_ids_in_team")
            fake.assert_not_called("get_distinct_ids_for_persons")

    def test_returns_empty_for_missing_distinct_ids(self):
        with fake_personhog_client():
            result = get_persons_mapped_by_distinct_id(1, ["nonexistent"])

            assert result == {}

    def test_cross_team_isolation(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=999, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["did-1"]
            )

            result = get_persons_mapped_by_distinct_id(1, ["did-1"])

            assert result == {}


# ── Delegation tests ────────────────────────────────────────────────


class TestGetPersonByPkOrUuid(SimpleTestCase):
    @patch("posthog.models.person.util.get_person_by_uuid")
    def test_routes_uuid_key_to_get_person_by_uuid(self, mock_get_by_uuid):
        mock_person = MagicMock()
        mock_get_by_uuid.return_value = mock_person

        result = get_person_by_pk_or_uuid(1, "550e8400-e29b-41d4-a716-446655440000")

        assert result == mock_person
        mock_get_by_uuid.assert_called_once_with(1, "550e8400-e29b-41d4-a716-446655440000")

    @patch("posthog.models.person.util.get_person_by_id")
    def test_routes_int_key_to_get_person_by_id(self, mock_get_by_id):
        mock_person = MagicMock()
        mock_get_by_id.return_value = mock_person

        result = get_person_by_pk_or_uuid(1, "42")

        assert result == mock_person
        mock_get_by_id.assert_called_once_with(1, 42)

    def test_returns_none_for_invalid_key(self):
        result = get_person_by_pk_or_uuid(1, "not-a-uuid-or-int")

        assert result is None

    @patch("posthog.models.person.util.get_person_by_uuid")
    def test_returns_none_when_uuid_lookup_finds_nothing(self, mock_get_by_uuid):
        mock_get_by_uuid.return_value = None

        result = get_person_by_pk_or_uuid(1, "550e8400-e29b-41d4-a716-446655440000")

        assert result is None

    @patch("posthog.models.person.util.get_person_by_id")
    def test_returns_none_when_id_lookup_finds_nothing(self, mock_get_by_id):
        mock_get_by_id.return_value = None

        result = get_person_by_pk_or_uuid(1, "42")

        assert result is None


# ── _personhog_routed unit tests ────────────────────────────────────


class TestPersonhogRouted(SimpleTestCase):
    @patch("posthog.personhog_client.gate.use_personhog", return_value=True)
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_calls_personhog_fn_and_increments_counter(self, mock_errors, mock_routing, _mock_gate):
        result = _personhog_routed("test_op", lambda: "personhog_result", lambda: "orm_result", team_id=1)

        assert result == "personhog_result"
        mock_routing.labels.assert_called_with(operation="test_op", source="personhog", client_name="posthog-django")
        mock_routing.labels.return_value.inc.assert_called_once()
        mock_errors.labels.assert_not_called()

    @patch("posthog.personhog_client.gate.use_personhog", return_value=False)
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_gate_off_uses_orm_and_increments_counter(self, mock_errors, mock_routing, _mock_gate):
        result = _personhog_routed("test_op", lambda: "personhog_result", lambda: "orm_result", team_id=1)

        assert result == "orm_result"
        mock_routing.labels.assert_called_with(operation="test_op", source="django_orm", client_name="posthog-django")
        mock_routing.labels.return_value.inc.assert_called_once()
        mock_errors.labels.assert_not_called()

    @patch("posthog.personhog_client.gate.use_personhog", return_value=True)
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_exception_falls_back_and_increments_both_counters(self, mock_errors, mock_routing, _mock_gate):
        def failing_fn():
            raise RuntimeError("grpc timeout")

        result = _personhog_routed("test_op", failing_fn, lambda: "orm_result", team_id=1)

        assert result == "orm_result"
        # Error counter incremented
        mock_errors.labels.assert_called_once_with(
            operation="test_op", source="personhog", error_type="grpc_error", client_name="posthog-django"
        )
        mock_errors.labels.return_value.inc.assert_called_once()
        # ORM routing counter incremented
        mock_routing.labels.assert_called_with(operation="test_op", source="django_orm", client_name="posthog-django")
        mock_routing.labels.return_value.inc.assert_called()

    @patch("posthog.personhog_client.gate.use_personhog", return_value=True)
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_returning_none_is_not_treated_as_failure(self, mock_errors, mock_routing, _mock_gate):
        result = _personhog_routed("test_op", lambda: None, lambda: "orm_result", team_id=1)

        assert result is None
        mock_routing.labels.assert_called_with(operation="test_op", source="personhog", client_name="posthog-django")
        mock_errors.labels.assert_not_called()


# ── Integration tests (dual-path) ──────────────────────────────────


@parameterized_class(("personhog",), [(False,), (True,)])
class TestGetPersonsMappedByDistinctIdIntegration(PersonhogTestMixin, BaseTest):
    def test_single_person_single_distinct_id(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1"], properties={"email": "a@example.com"})

        result = get_persons_mapped_by_distinct_id(self.team.pk, ["did-1"])

        assert "did-1" in result
        assert str(result["did-1"].uuid) == str(person.uuid)
        assert result["did-1"].properties == {"email": "a@example.com"}
        assert result["did-1"].distinct_ids == ["did-1"]
        self._assert_personhog_called("get_persons_by_distinct_ids_in_team")

    def test_single_person_multiple_distinct_ids(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1", "did-2"])

        result = get_persons_mapped_by_distinct_id(self.team.pk, ["did-1", "did-2"])

        # Both distinct_ids should map to the same person
        assert len(result) == 2
        assert str(result["did-1"].uuid) == str(person.uuid)
        assert str(result["did-2"].uuid) == str(person.uuid)
        # Each entry should carry only the distinct_id that was used as the key
        assert result["did-1"].distinct_ids == ["did-1"]
        assert result["did-2"].distinct_ids == ["did-2"]

    def test_multiple_persons(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["alice"], properties={"name": "Alice"})
        p2 = self._seed_person(team=self.team, distinct_ids=["bob"], properties={"name": "Bob"})

        result = get_persons_mapped_by_distinct_id(self.team.pk, ["alice", "bob"])

        assert str(result["alice"].uuid) == str(p1.uuid)
        assert str(result["bob"].uuid) == str(p2.uuid)

    def test_missing_distinct_ids_returns_empty(self):
        result = get_persons_mapped_by_distinct_id(self.team.pk, ["nonexistent"])

        assert result == {}

    def test_cross_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        self._seed_person(team=other_team, distinct_ids=["shared_did"])

        result = get_persons_mapped_by_distinct_id(self.team.pk, ["shared_did"])

        assert result == {}
