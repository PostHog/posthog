from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person.util import (
    _fetch_persons_by_distinct_ids_via_personhog,
    get_persons_by_distinct_ids,
    get_persons_by_uuids,
)


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

        team = MagicMock()
        team.pk = 1
        uuids = ["uuid-1", "uuid-2"]

        result = get_persons_by_uuids(team, uuids)

        if personhog_data is not None and gate_on:
            assert result == personhog_data
            mock_objects.db_manager.assert_not_called()
        else:
            assert result == mock_qs

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
                patch("django.db.models.query.Prefetch"),
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


class TestFetchPersonsByDistinctIdsFiltering(SimpleTestCase):
    @patch("posthog.personhog_client.client.get_personhog_client")
    def test_missing_persons_are_excluded(self, mock_get_client):
        real_person = SimpleNamespace(
            id=42,
            uuid="550e8400-e29b-41d4-a716-446655440000",
            team_id=1,
            properties=b'{"email": "real@example.com"}',
            is_identified=True,
            created_at=1700000000000,
            last_seen_at=0,
        )
        # Entry with person=None (unresolved distinct_id)
        missing_entry = SimpleNamespace(distinct_id="ghost", person=None)
        # Entry with a default/empty person (id=0)
        empty_entry = SimpleNamespace(distinct_id="empty", person=SimpleNamespace(id=0))
        # Entry with a real person
        valid_entry = SimpleNamespace(distinct_id="real_did", person=real_person)

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get_persons_by_distinct_ids_in_team.return_value = SimpleNamespace(
            results=[missing_entry, empty_entry, valid_entry]
        )
        mock_client.get_distinct_ids_for_persons.return_value = SimpleNamespace(
            person_distinct_ids=[SimpleNamespace(person_id=42, distinct_ids=[SimpleNamespace(distinct_id="real_did")])]
        )

        result = _fetch_persons_by_distinct_ids_via_personhog(team_id=1, distinct_ids=["ghost", "empty", "real_did"])

        assert len(result) == 1
        assert result[0].id == 42
        assert result[0].properties == {"email": "real@example.com"}
        assert result[0].distinct_ids == ["real_did"]

        # Verify only the valid person_id was sent to get_distinct_ids_for_persons
        call_args = mock_client.get_distinct_ids_for_persons.call_args
        assert call_args[0][0].person_ids == [42]
