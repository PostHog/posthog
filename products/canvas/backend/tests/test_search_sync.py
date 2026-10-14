from uuid import uuid4

from django.test import TransactionTestCase

from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.models.scoping import team_scope

from products.canvas.backend.facade import testing as canvas_testing
from products.tasks.backend.facade.api import search_tasks
from products.tasks.backend.models import Channel


class TestCanvasSearchSync(TransactionTestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Search Org")
        self.team = Team.objects.create(organization=self.organization, name="Search Team")
        self.user = User.objects.create(email="search@example.com", distinct_id="search-user")
        self.enterContext(team_scope(self.team.id))

    def make_canvas(self, name="Run rate", **kwargs):
        channel = kwargs.pop("channel", None) or Channel.objects.create(
            team=self.team, name=f"canvas-space-{uuid4()}", created_by=self.user
        )
        return canvas_testing.create_canvas(
            team_id=self.team.id, channel_id=channel.id, name=name, created_by_id=self.user.id, **kwargs
        )

    @parameterized.expand([("channel",), ("channel_id",)])
    def test_a_canvas_moved_into_a_private_space_leaves_team_search(self, channel_field):
        shared = Channel.objects.create(team=self.team, name="canvas-home", created_by=self.user)
        private = Channel.objects.create(
            team=self.team,
            name="me",
            channel_type=Channel.ChannelType.PERSONAL,
            created_by=self.user,
        )
        canvas_id = canvas_testing.create_canvas(team_id=self.team.id, name="Release checklist", channel_id=shared.id)
        teammate = User.objects.create(email="teammate@example.com", distinct_id="teammate-search-user")
        self.assertEqual(len(search_tasks(self.team.id, teammate.id, "release checklist")), 1)

        canvas_testing.save_canvas_fields(
            canvas_id, team_id=self.team.id, update_fields=[channel_field], channel_id=private.id
        )

        self.assertEqual(search_tasks(self.team.id, teammate.id, "release checklist"), [])
        self.assertEqual(
            search_tasks(self.team.id, self.user.id, "release checklist")[0]["channel_id"],
            str(private.id),
        )

    def test_finds_a_canvas_by_name(self):
        channel = Channel.objects.create(team=self.team, name="canvas-space", created_by=self.user)
        canvas_id = self.make_canvas(channel=channel)

        result = search_tasks(self.team.id, self.user.id, "run rate")[0]

        self.assertEqual(result["kind"], "canvas")
        self.assertEqual(result["metadata"]["canvas_id"], str(canvas_id))
        self.assertEqual(result["channel_id"], str(channel.id))

    def test_renamed_and_deleted_canvases_follow_the_canvas(self):
        canvas_id = self.make_canvas(name="Run rate")

        canvas_testing.save_canvas_fields(canvas_id, team_id=self.team.id, update_fields=["name"], name="Burn rate")
        self.assertEqual(search_tasks(self.team.id, self.user.id, "run rate"), [])
        self.assertEqual(
            search_tasks(self.team.id, self.user.id, "burn rate")[0]["metadata"]["canvas_id"], str(canvas_id)
        )

        canvas_testing.save_canvas_fields(canvas_id, team_id=self.team.id, update_fields=["deleted"], deleted=True)
        self.assertEqual(search_tasks(self.team.id, self.user.id, "burn rate"), [])

    def test_notebook_widget_canvases_stay_out_of_search(self):
        self.make_canvas(name="Run widget", source_policy="notebook_widget")

        self.assertEqual(search_tasks(self.team.id, self.user.id, "run widget"), [])
