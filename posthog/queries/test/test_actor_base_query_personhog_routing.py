from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.queries.actor_base_query import get_people


class TestGetPeopleRouting(SimpleTestCase):
    @patch("posthog.queries.actor_base_query._fetch_people_via_personhog")
    @patch("posthog.queries.actor_base_query.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.queries.actor_base_query.serialize_people")
    def test_personhog_success(self, mock_serialize, mock_routing_counter, mock_fetch_personhog):
        personhog_persons = [MagicMock(), MagicMock()]
        mock_fetch_personhog.return_value = personhog_persons
        mock_serialize.return_value = [{"type": "person", "id": "test"}]

        team = MagicMock()
        team.pk = 1

        result_persons, _ = get_people(team, ["uuid-1", "uuid-2"])

        assert result_persons == personhog_persons
        mock_routing_counter.labels.assert_called_with(
            operation="get_people", source="personhog", client_name="posthog-django"
        )

    @patch("posthog.queries.actor_base_query._fetch_people_via_personhog")
    @patch("posthog.queries.actor_base_query.serialize_people")
    def test_personhog_failure_raises(self, mock_serialize, mock_fetch_personhog):
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        team = MagicMock()
        team.pk = 1

        with self.assertRaises(RuntimeError):
            get_people(team, ["uuid-1", "uuid-2"])
