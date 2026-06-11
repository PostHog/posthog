from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.models.team.util import _delete_group_type_mappings_for_teams, _delete_groups_for_teams

_CLIENT_PATCH = "posthog.personhog_client.client.get_personhog_client"


class TestDeleteGroupsForTeams(SimpleTestCase):
    @patch(_CLIENT_PATCH)
    def test_deletes_via_personhog_per_team(self, mock_get_client):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.deleted_count = 0
        mock_client.delete_groups_batch_for_team.return_value = resp
        mock_get_client.return_value = mock_client

        _delete_groups_for_teams([1, 2, 3])

        assert mock_client.delete_groups_batch_for_team.call_count == 3

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

        _delete_groups_for_teams([42])

        assert mock_client.delete_groups_batch_for_team.call_count == 3

    @patch(_CLIENT_PATCH)
    def test_uses_batch_size_10000(self, mock_get_client):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.deleted_count = 0
        mock_client.delete_groups_batch_for_team.return_value = resp
        mock_get_client.return_value = mock_client

        _delete_groups_for_teams([42])

        req = mock_client.delete_groups_batch_for_team.call_args[0][0]
        assert req.batch_size == 10000
        assert req.team_id == 42

    @patch("posthog.models.team.util._raw_delete")
    @patch(_CLIENT_PATCH)
    def test_falls_back_to_orm_when_client_none(self, mock_get_client, mock_raw_delete):
        mock_get_client.return_value = None

        _delete_groups_for_teams([42])

        mock_raw_delete.assert_called_once()

    @patch("posthog.models.team.util._raw_delete")
    @patch(_CLIENT_PATCH)
    def test_falls_back_to_orm_on_error(self, mock_get_client, mock_raw_delete):
        mock_client = MagicMock()
        mock_client.delete_groups_batch_for_team.side_effect = Exception("rpc failed")
        mock_get_client.return_value = mock_client

        _delete_groups_for_teams([42])

        mock_raw_delete.assert_called_once()

    @patch(_CLIENT_PATCH)
    def test_empty_list_does_nothing(self, mock_get_client):
        _delete_groups_for_teams([])

        mock_get_client.return_value.delete_groups_batch_for_team.assert_not_called()


class TestDeleteGroupTypeMappingsForTeams(SimpleTestCase):
    @patch(_CLIENT_PATCH)
    def test_deletes_via_personhog_per_team(self, mock_get_client):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.deleted_count = 0
        mock_client.delete_group_type_mappings_batch_for_team.return_value = resp
        mock_get_client.return_value = mock_client

        _delete_group_type_mappings_for_teams([1, 2, 3])

        assert mock_client.delete_group_type_mappings_batch_for_team.call_count == 3

    @patch(_CLIENT_PATCH)
    def test_loops_until_zero_deleted(self, mock_get_client):
        mock_client = MagicMock()
        resp1 = MagicMock()
        resp1.deleted_count = 5
        resp2 = MagicMock()
        resp2.deleted_count = 0
        mock_client.delete_group_type_mappings_batch_for_team.side_effect = [resp1, resp2]
        mock_get_client.return_value = mock_client

        _delete_group_type_mappings_for_teams([42])

        assert mock_client.delete_group_type_mappings_batch_for_team.call_count == 2

    @patch(_CLIENT_PATCH)
    def test_uses_batch_size_10000(self, mock_get_client):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.deleted_count = 0
        mock_client.delete_group_type_mappings_batch_for_team.return_value = resp
        mock_get_client.return_value = mock_client

        _delete_group_type_mappings_for_teams([42])

        req = mock_client.delete_group_type_mappings_batch_for_team.call_args[0][0]
        assert req.batch_size == 10000
        assert req.team_id == 42

    @patch("posthog.models.team.util._raw_delete")
    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch(_CLIENT_PATCH)
    def test_falls_back_to_orm_when_client_none(self, mock_get_client, mock_objects, mock_raw_delete):
        mock_get_client.return_value = None

        _delete_group_type_mappings_for_teams([42])

        mock_raw_delete.assert_called_once()

    @patch("posthog.models.team.util._raw_delete")
    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch(_CLIENT_PATCH)
    def test_falls_back_to_orm_on_error(self, mock_get_client, mock_objects, mock_raw_delete):
        mock_client = MagicMock()
        mock_client.delete_group_type_mappings_batch_for_team.side_effect = Exception("rpc failed")
        mock_get_client.return_value = mock_client

        _delete_group_type_mappings_for_teams([42])

        mock_raw_delete.assert_called_once()

    @patch(_CLIENT_PATCH)
    def test_empty_list_does_nothing(self, mock_get_client):
        _delete_group_type_mappings_for_teams([])

        mock_get_client.return_value.delete_group_type_mappings_batch_for_team.assert_not_called()
