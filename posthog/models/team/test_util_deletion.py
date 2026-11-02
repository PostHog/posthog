from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.team import Team
from posthog.models.team.util import (
    RETIRED_LOOP_TABLES,
    TeamPurgeStopped,
    _delete_event_properties_for_teams,
    _delete_group_type_mappings_for_teams,
    _delete_groups_for_teams,
    _delete_hash_key_overrides_for_teams,
    _delete_retired_loops_for_teams,
)

from products.event_definitions.backend.models import EventProperty

_CLIENT_PATCH = "posthog.personhog_client.client.get_personhog_client"


class TestDeleteRetiredLoopsForTeams(SimpleTestCase):
    @patch("posthog.models.team.util.connections")
    def test_deletes_existing_tables_child_first(self, mock_connections):
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [(table,) for table in RETIRED_LOOP_TABLES]
        cursor.rowcount = 0
        mock_connections.__getitem__.return_value.cursor.return_value = cursor

        _delete_retired_loops_for_teams([1, 2])

        delete_statements = [call.args for call in cursor.execute.call_args_list if call.args[0].startswith("DELETE")]
        assert [args[0].split('"')[1] for args in delete_statements] == list(RETIRED_LOOP_TABLES)
        assert all(args[1] == [[1, 2], 10000] for args in delete_statements)

    @patch("posthog.models.team.util.connections")
    def test_skips_tables_that_no_longer_exist(self, mock_connections):
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [(None,) for _ in RETIRED_LOOP_TABLES]
        mock_connections.__getitem__.return_value.cursor.return_value = cursor

        _delete_retired_loops_for_teams([1])

        assert not any(call.args[0].startswith("DELETE") for call in cursor.execute.call_args_list)


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
        req = mock_client.delete_groups_batch_for_team.call_args[0][0]
        assert req.batch_size == 10000

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
        req = mock_client.delete_group_type_mappings_batch_for_team.call_args[0][0]
        assert req.batch_size == 10000

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
    def test_empty_list_does_nothing(self, mock_get_client):
        _delete_group_type_mappings_for_teams([])

        mock_get_client.return_value.delete_group_type_mappings_batch_for_team.assert_not_called()


class TestDeleteHashKeyOverridesForTeams(SimpleTestCase):
    @patch(_CLIENT_PATCH)
    def test_deletes_via_personhog(self, mock_get_client):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.deleted_count = 0
        mock_client.delete_hash_key_overrides_by_teams.return_value = resp
        mock_get_client.return_value = mock_client

        _delete_hash_key_overrides_for_teams([1, 2, 3])

        assert mock_client.delete_hash_key_overrides_by_teams.call_count == 1
        req = mock_client.delete_hash_key_overrides_by_teams.call_args[0][0]
        assert list(req.team_ids) == [1, 2, 3]
        assert req.batch_size == 2000

    @patch(_CLIENT_PATCH)
    def test_loops_until_zero_deleted(self, mock_get_client):
        mock_client = MagicMock()
        resp1 = MagicMock()
        resp1.deleted_count = 10000
        resp2 = MagicMock()
        resp2.deleted_count = 3
        resp3 = MagicMock()
        resp3.deleted_count = 0
        mock_client.delete_hash_key_overrides_by_teams.side_effect = [resp1, resp2, resp3]
        mock_get_client.return_value = mock_client

        _delete_hash_key_overrides_for_teams([42])

        assert mock_client.delete_hash_key_overrides_by_teams.call_count == 3

    @patch(_CLIENT_PATCH)
    def test_empty_list_does_nothing(self, mock_get_client):
        _delete_hash_key_overrides_for_teams([])

        mock_get_client.return_value.delete_hash_key_overrides_by_teams.assert_not_called()


@patch("posthog.models.team.util.time.sleep")
class TestDeleteEventPropertiesForTeams(BaseTest):
    def _create_event_properties(self, team: Team) -> None:
        # Three rows share one property, so small batches end inside a run of equal property names.
        pairs = [("e1", "shared"), ("e2", "shared"), ("e3", "shared"), ("e1", "a"), ("e2", "z")]
        EventProperty.objects.bulk_create(EventProperty(team=team, event=e, property=p) for e, p in pairs)

    @parameterized.expand([(1,), (2,), (3,), (10000,)])
    def test_deletes_every_row_of_the_team_and_no_other(self, _sleep: MagicMock, batch_size: int) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._create_event_properties(self.team)
        self._create_event_properties(other_team)

        _delete_event_properties_for_teams([self.team.id], batch_size=batch_size)

        assert not EventProperty.objects.filter(team_id=self.team.id).exists()
        assert EventProperty.objects.filter(team_id=other_team.id).count() == 5

    def test_stop_ends_the_purge_between_batches(self, _sleep: MagicMock) -> None:
        self._create_event_properties(self.team)
        stops = iter([False, True])

        with self.assertRaises(TeamPurgeStopped):
            _delete_event_properties_for_teams([self.team.id], should_stop=lambda: next(stops), batch_size=2)

        assert EventProperty.objects.filter(team_id=self.team.id).count() == 3
