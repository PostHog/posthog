from uuid import uuid4

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.models.scoping import team_scope

from products.canvas.backend.facade import api, testing
from products.canvas.backend.facade.contracts import CanvasSearchRecord
from products.tasks.backend.models import Channel


class TestCanvasFacade(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Facade Org")
        self.team = Team.objects.create(organization=self.organization, name="Facade Team")
        self.user = User.objects.create(email="facade@example.com", distinct_id="facade-user")
        self.enterContext(team_scope(self.team.id))
        self.channel = Channel.objects.create(team=self.team, name="canvases", created_by=self.user)

    def _canvas(self, **fields):
        return testing.create_canvas(
            team_id=self.team.id,
            channel_id=self.channel.id,
            name=fields.pop("name", "Release checklist"),
            created_by_id=self.user.id,
            **fields,
        )

    def test_searchable_canvas_returns_a_record_for_a_standard_canvas(self):
        canvas_id = self._canvas()

        assert api.searchable_canvas(canvas_id) == CanvasSearchRecord(
            id=canvas_id,
            team_id=self.team.id,
            name="Release checklist",
            channel_id=self.channel.id,
            kind="freeform",
            template_id="freeform",
        )

    @parameterized.expand(
        [
            ("deleted", {"deleted": True}),
            ("notebook_widget", {"source_policy": "notebook_widget"}),
        ]
    )
    def test_searchable_canvas_hides_canvases_search_must_not_show(self, _name, fields):
        assert api.searchable_canvas(self._canvas(**fields)) is None

    def test_searchable_canvas_returns_none_for_an_unknown_id(self):
        assert api.searchable_canvas(uuid4()) is None

    def test_list_canvas_ids_returns_every_canvas_of_the_team(self):
        ids = {self._canvas(name="A"), self._canvas(name="B", deleted=True)}

        assert set(api.list_canvas_ids(self.team.id)) == ids

    def test_channel_has_canvases_ignores_deleted_canvases(self):
        empty = Channel.objects.create(team=self.team, name="empty", created_by=self.user)
        self._canvas(deleted=True)
        testing.create_canvas(team_id=self.team.id, channel_id=empty.id, name="gone", deleted=True)

        assert api.channel_has_canvases(team_id=self.team.id, channel_id=self.channel.id) is False
        self._canvas()
        assert api.channel_has_canvases(team_id=self.team.id, channel_id=self.channel.id) is True
        assert api.channel_has_canvases(team_id=self.team.id, channel_id=empty.id) is False

    def test_canvas_is_visible_follows_channel_visibility_and_deletion(self):
        other = User.objects.create(email="other@example.com", distinct_id="other-user")
        personal = Channel.objects.create(
            team=self.team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=self.user
        )
        private_id = testing.create_canvas(team_id=self.team.id, channel_id=personal.id, name="mine")
        deleted_id = self._canvas(deleted=True)
        public_id = self._canvas()

        assert api.canvas_is_visible(team_id=self.team.id, canvas_id=public_id, user_id=other.id) is True
        assert api.canvas_is_visible(team_id=self.team.id, canvas_id=private_id, user_id=self.user.id) is True
        assert api.canvas_is_visible(team_id=self.team.id, canvas_id=private_id, user_id=other.id) is False
        assert api.canvas_is_visible(team_id=self.team.id, canvas_id=deleted_id, user_id=self.user.id) is False

    def test_save_canvas_fields_writes_only_the_named_fields(self):
        canvas_id = self._canvas()

        testing.save_canvas_fields(canvas_id, update_fields=["name"], name="Burn rate", deleted=True)

        record = api.searchable_canvas(canvas_id)
        assert record is not None
        assert record.name == "Burn rate"
