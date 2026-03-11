from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person.util import get_persons_by_distinct_ids, get_persons_by_uuids


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
