from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.models.team.util import (
    _delete_group_type_mappings_for_team_via_personhog,
    _delete_group_type_mappings_for_teams,
    _delete_groups_for_team_via_personhog,
    _delete_groups_for_teams,
)

_CLIENT_PATCH = "posthog.personhog_client.client.get_personhog_client"
_ROUTED_PATCH = "posthog.models.person.util._personhog_routed"


class TestDeleteGroupsForTeams(SimpleTestCase):
    @patch(_ROUTED_PATCH)
    def test_calls_personhog_routed_per_team(self, mock_routed):
        _delete_groups_for_teams([1, 2, 3])

        assert mock_routed.call_count == 3
        for c in mock_routed.call_args_list:
            assert c[0][0] == "delete_groups_for_team"
            assert "team_id" in c[1]

    @patch(_ROUTED_PATCH)
    def test_passes_correct_team_ids(self, mock_routed):
        _delete_groups_for_teams([10, 20])

        team_ids = [c[1]["team_id"] for c in mock_routed.call_args_list]
        assert team_ids == [10, 20]

    @patch(_ROUTED_PATCH)
    def test_empty_list_does_nothing(self, mock_routed):
        _delete_groups_for_teams([])

        mock_routed.assert_not_called()


class TestDeleteGroupsForTeamViaPersonhog(SimpleTestCase):
    @patch(_CLIENT_PATCH)
    def test_loops_until_zero_deleted(self, mock_get_client):
        mock_client = MagicMock()
        resp1 = MagicMock()
        resp1.deleted_count = 10000
        resp2 = MagicMock()
        resp2.deleted_count = 500
        resp3 = MagicMock()
        resp3.deleted_count = 0
        mock_client.delete_groups_batch_for_team.side_effect = [resp1, resp2, resp3]
        mock_get_client.return_value = mock_client

        _delete_groups_for_team_via_personhog(42)

        assert mock_client.delete_groups_batch_for_team.call_count == 3

    @patch(_CLIENT_PATCH)
    def test_single_batch_when_few_records(self, mock_get_client):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.deleted_count = 0
        mock_client.delete_groups_batch_for_team.return_value = resp
        mock_get_client.return_value = mock_client

        _delete_groups_for_team_via_personhog(42)

        mock_client.delete_groups_batch_for_team.assert_called_once()

    @patch(_CLIENT_PATCH)
    def test_raises_if_client_none(self, mock_get_client):
        mock_get_client.return_value = None

        with self.assertRaises(RuntimeError, msg="personhog client not configured"):
            _delete_groups_for_team_via_personhog(42)

    @patch(_CLIENT_PATCH)
    def test_uses_batch_size_10000(self, mock_get_client):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.deleted_count = 0
        mock_client.delete_groups_batch_for_team.return_value = resp
        mock_get_client.return_value = mock_client

        _delete_groups_for_team_via_personhog(42)

        req = mock_client.delete_groups_batch_for_team.call_args[0][0]
        assert req.batch_size == 10000
        assert req.team_id == 42


class TestDeleteGroupTypeMappingsForTeams(SimpleTestCase):
    @patch(_ROUTED_PATCH)
    def test_calls_personhog_routed_per_team(self, mock_routed):
        _delete_group_type_mappings_for_teams([1, 2, 3])

        assert mock_routed.call_count == 3
        for c in mock_routed.call_args_list:
            assert c[0][0] == "delete_group_type_mappings_for_team"
            assert "team_id" in c[1]

    @patch(_ROUTED_PATCH)
    def test_passes_correct_team_ids(self, mock_routed):
        _delete_group_type_mappings_for_teams([10, 20])

        team_ids = [c[1]["team_id"] for c in mock_routed.call_args_list]
        assert team_ids == [10, 20]

    @patch(_ROUTED_PATCH)
    def test_empty_list_does_nothing(self, mock_routed):
        _delete_group_type_mappings_for_teams([])

        mock_routed.assert_not_called()


class TestDeleteGroupTypeMappingsForTeamViaPersonhog(SimpleTestCase):
    @patch(_CLIENT_PATCH)
    def test_loops_until_zero_deleted(self, mock_get_client):
        mock_client = MagicMock()
        resp1 = MagicMock()
        resp1.deleted_count = 5
        resp2 = MagicMock()
        resp2.deleted_count = 0
        mock_client.delete_group_type_mappings_batch_for_team.side_effect = [resp1, resp2]
        mock_get_client.return_value = mock_client

        _delete_group_type_mappings_for_team_via_personhog(42)

        assert mock_client.delete_group_type_mappings_batch_for_team.call_count == 2

    @patch(_CLIENT_PATCH)
    def test_raises_if_client_none(self, mock_get_client):
        mock_get_client.return_value = None

        with self.assertRaises(RuntimeError, msg="personhog client not configured"):
            _delete_group_type_mappings_for_team_via_personhog(42)

    @patch(_CLIENT_PATCH)
    def test_uses_batch_size_10000(self, mock_get_client):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.deleted_count = 0
        mock_client.delete_group_type_mappings_batch_for_team.return_value = resp
        mock_get_client.return_value = mock_client

        _delete_group_type_mappings_for_team_via_personhog(42)

        req = mock_client.delete_group_type_mappings_batch_for_team.call_args[0][0]
        assert req.batch_size == 10000
        assert req.team_id == 42
