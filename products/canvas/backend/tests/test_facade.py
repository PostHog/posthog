from uuid import uuid4

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.models.scoping import team_scope

from products.canvas.backend.facade import access, search, testing
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

        assert search.searchable_canvas(team_id=self.team.id, canvas_id=canvas_id) == CanvasSearchRecord(
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
        assert search.searchable_canvas(team_id=self.team.id, canvas_id=self._canvas(**fields)) is None

    def test_searchable_canvas_returns_none_for_an_unknown_id(self):
        assert search.searchable_canvas(team_id=self.team.id, canvas_id=uuid4()) is None

    def test_list_canvas_ids_returns_every_canvas_of_the_team(self):
        ids = {self._canvas(name="A"), self._canvas(name="B", deleted=True)}

        assert set(search.list_canvas_ids(self.team.id)) == ids

    def test_channel_has_canvases_ignores_deleted_canvases(self):
        empty = Channel.objects.create(team=self.team, name="empty", created_by=self.user)
        self._canvas(deleted=True)
        testing.create_canvas(team_id=self.team.id, channel_id=empty.id, name="gone", deleted=True)

        assert access.channel_has_canvases(team_id=self.team.id, channel_id=self.channel.id) is False
        self._canvas()
        assert access.channel_has_canvases(team_id=self.team.id, channel_id=self.channel.id) is True
        assert access.channel_has_canvases(team_id=self.team.id, channel_id=empty.id) is False

    def test_canvas_is_visible_follows_channel_visibility_and_deletion(self):
        other = User.objects.create(email="other@example.com", distinct_id="other-user")
        personal = Channel.objects.create(
            team=self.team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=self.user
        )
        private_id = testing.create_canvas(team_id=self.team.id, channel_id=personal.id, name="mine")
        deleted_id = self._canvas(deleted=True)
        public_id = self._canvas()

        assert access.canvas_is_visible(team_id=self.team.id, canvas_id=public_id, user_id=other.id) is True
        assert access.canvas_is_visible(team_id=self.team.id, canvas_id=private_id, user_id=self.user.id) is True
        assert access.canvas_is_visible(team_id=self.team.id, canvas_id=private_id, user_id=other.id) is False
        assert access.canvas_is_visible(team_id=self.team.id, canvas_id=deleted_id, user_id=self.user.id) is False

    def test_save_canvas_fields_writes_only_the_named_fields(self):
        canvas_id = self._canvas()

        testing.save_canvas_fields(
            canvas_id, team_id=self.team.id, update_fields=["name"], name="Burn rate", deleted=True
        )

        record = search.searchable_canvas(team_id=self.team.id, canvas_id=canvas_id)
        assert record is not None
        assert record.name == "Burn rate"

    def _private_space(self, owner, members):
        channel = Channel.objects.create(
            team=self.team, name=f"private-{uuid4()}", channel_type=Channel.ChannelType.PRIVATE, created_by=owner
        )
        for member in members:
            channel.memberships.create(team=self.team, user=member)
        return channel

    @parameterized.expand(
        [
            ("member_of_the_private_space", {}, True),
            ("sandbox_of_a_member_who_did_not_create_it", {"sandbox": True}, False),
            ("sandbox_of_its_creator", {"sandbox": True, "as_creator": True}, True),
            ("task_that_built_it", {"task": "builder"}, True),
            ("task_that_did_not_build_it", {"task": "other"}, False),
            ("space_deleted", {"space_deleted": True}, False),
        ]
    )
    def test_canvas_comments_accessible_follows_space_sandbox_and_task(self, _name, case, expected):
        creator = User.objects.create(email=f"creator-{uuid4()}@example.com", distinct_id=str(uuid4()))
        member = User.objects.create(email=f"member-{uuid4()}@example.com", distinct_id=str(uuid4()))
        space = self._private_space(creator, [creator, member])
        builder_task_id = uuid4()
        canvas_id = testing.create_canvas(
            team_id=self.team.id,
            channel_id=space.id,
            name="Private plan",
            created_by_id=creator.id,
            generation_task_id=builder_task_id,
        )
        if case.get("space_deleted"):
            Channel.objects.filter(id=space.id).update(deleted=True)
        task_id = {"builder": builder_task_id, "other": uuid4()}.get(case.get("task", ""))

        assert (
            access.canvas_comments_accessible(
                team_id=self.team.id,
                user_id=(creator if case.get("as_creator") else member).id,
                canvas_id=str(canvas_id),
                task_id=task_id,
                sandbox=case.get("sandbox", False),
            )
            is expected
        )

    def test_visible_canvas_user_ids_keeps_only_users_who_can_see_the_space(self):
        member = User.objects.create(email="member@example.com", distinct_id="member-user")
        outsider = User.objects.create(email="outsider@example.com", distinct_id="outsider-user")
        candidates = {self.user.id, member.id, outsider.id}
        private_id = testing.create_canvas(
            team_id=self.team.id,
            channel_id=self._private_space(self.user, [self.user, member]).id,
            name="Private plan",
            created_by_id=self.user.id,
        )

        assert (
            access.visible_canvas_user_ids(team_id=self.team.id, canvas_id=str(self._canvas()), user_ids=candidates)
            == candidates
        )
        assert access.visible_canvas_user_ids(team_id=self.team.id, canvas_id=str(private_id), user_ids=candidates) == {
            self.user.id,
            member.id,
        }

    def test_live_visible_canvas_ids_drops_ids_that_are_not_visible_canvases(self):
        public_id = self._canvas()
        deleted_id = self._canvas(deleted=True)

        assert access.live_visible_canvas_ids(
            self.team.id, self.user.id, ["not-a-uuid", str(public_id), str(deleted_id)]
        ) == {str(public_id)}

    def test_canvas_owner_activity_skips_deleted_and_ownerless_canvases(self):
        self._canvas()
        self._canvas(deleted=True)
        testing.create_canvas(team_id=self.team.id, channel_id=self.channel.id, name="Ownerless")

        activity = access.canvas_owner_activity(team_id=self.team.id, channel_ids=[self.channel.id])

        assert [(row.channel_id, row.created_by_id) for row in activity] == [(self.channel.id, self.user.id)]
