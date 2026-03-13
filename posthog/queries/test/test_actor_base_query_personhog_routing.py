from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.queries.actor_base_query import get_people


class TestGetPeopleRouting(SimpleTestCase):
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
    @patch("posthog.queries.actor_base_query._fetch_people_via_personhog")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.queries.actor_base_query.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.queries.actor_base_query.PERSONHOG_ROUTING_ERRORS_TOTAL")
    @patch("posthog.queries.actor_base_query.serialize_people")
    def test_routing(
        self,
        _name,
        gate_on,
        grpc_exception,
        expected_source,
        mock_serialize,
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

        mock_serialize.return_value = [{"type": "person", "id": "test"}]

        team = MagicMock()
        team.pk = 1
        people_ids = ["uuid-1", "uuid-2"]

        if gate_on and grpc_exception is None:
            result_persons, _ = get_people(team, people_ids)
            assert result_persons == personhog_persons
        else:
            with (
                patch("posthog.queries.actor_base_query.Person.objects") as mock_person_objects,
                patch("posthog.queries.actor_base_query.PersonDistinctId.objects"),
                patch("posthog.queries.actor_base_query.Prefetch"),
                patch("posthog.queries.actor_base_query.Subquery"),
            ):
                mock_qs = MagicMock()
                mock_person_objects.db_manager.return_value.filter.return_value.prefetch_related.return_value.order_by.return_value.only.return_value = mock_qs

                result_persons, _ = get_people(team, people_ids)
                assert result_persons == mock_qs

        mock_routing_counter.labels.assert_called_with(
            operation="get_people", source=expected_source, client_name="posthog-django"
        )

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()
