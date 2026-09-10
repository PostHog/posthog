from posthog.test.base import APIBaseTest

from parameterized import parameterized

from products.canvas.backend.models import Sketchpad
from products.tasks.backend.models import Channel


class TestSketchpadAccess(APIBaseTest):
    def _board(self, channel: Channel, *, mine: bool) -> Sketchpad:
        return Sketchpad.objects.for_team(self.team.id).create(
            team=self.team,
            channel=channel,
            name="Sketchpad",
            created_by=self.user if mine else self._create_user("someone-else@example.com"),
        )

    @parameterized.expand([("own_board", True, 204), ("other_board", False, 404)])
    def test_only_the_creator_deletes_a_board(self, _name: str, mine: bool, expected: int) -> None:
        channel = Channel.objects.for_team(self.team.id).create(
            team=self.team, name="general", channel_type=Channel.ChannelType.PUBLIC
        )
        sketchpad = self._board(channel, mine=mine)

        response = self.client.delete(f"/api/projects/{self.team.id}/sketchpads/{sketchpad.id}/")

        assert response.status_code == expected
        sketchpad.refresh_from_db()
        assert sketchpad.deleted is (expected == 204)

    def test_a_collaborator_edits_a_board_it_cannot_delete(self) -> None:
        channel = Channel.objects.for_team(self.team.id).create(
            team=self.team, name="general", channel_type=Channel.ChannelType.PUBLIC
        )
        sketchpad = self._board(channel, mine=False)

        response = self.client.post(
            f"/api/projects/{self.team.id}/sketchpads/{sketchpad.id}/ops/",
            {
                "base_seq": 0,
                "ops": [{"op_id": "edit", "op": {"type": "set_state", "key": "note", "value": "new"}}],
                "actor": {"kind": "user"},
            },
            format="json",
        )

        assert response.status_code == 200
        assert self.client.delete(f"/api/projects/{self.team.id}/sketchpads/{sketchpad.id}/").status_code == 404
