from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, BaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.unfiled_file_saver import save_unfiled_files
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.scoping import team_scope
from posthog.models.user import User
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.canvas.backend.models import Canvas
from products.tasks.backend.models import Channel


class TestCanvasFileSystem(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(team_scope(self.team.id))
        self.channel = Channel.objects.create(team=self.team, name="general", created_by=self.user)

    def _entry(self, canvas: Canvas) -> FileSystem | None:
        return FileSystem.objects.filter(team=self.team, type="canvas", ref=str(canvas.id)).first()

    def test_freeform_canvas_lifecycle(self) -> None:
        canvas = Canvas.objects.create(team=self.team, channel=self.channel, name="Run rate", created_by=self.user)
        entry = self._entry(canvas)
        assert entry is not None
        self.assertEqual(entry.path, "Unfiled/Canvases/Run rate")
        self.assertEqual(entry.href, f"/canvases/{canvas.id}")
        self.assertEqual(entry.created_by, self.user)

        canvas.deleted = True
        canvas.save()
        self.assertIsNone(self._entry(canvas))

    @parameterized.expand(
        [
            ("component", {"kind": Canvas.KIND_COMPONENT}),
            ("grid", {"kind": Canvas.KIND_GRID}),
            ("notebook_widget", {"source_policy": Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET}),
        ]
    )
    def test_non_analysis_canvases_stay_out(self, _name: str, overrides: dict) -> None:
        canvas = Canvas.objects.create(
            team=self.team, channel=self.channel, name="Widget", created_by=self.user, **overrides
        )
        self.assertIsNone(self._entry(canvas))
        self.assertEqual(Canvas.get_file_system_unfiled(self.team).count(), 0)

    def test_unfiled_saver_files_existing_canvases(self) -> None:
        canvas = Canvas.objects.create(team=self.team, channel=self.channel, name="Older", created_by=self.user)
        FileSystem.objects.all().delete()

        created = save_unfiled_files(self.team, self.user, file_type="canvas")

        self.assertEqual([entry.ref for entry in created], [str(canvas.id)])
        self.assertEqual(self._entry(canvas).path, "Unfiled/Canvases/Older")  # type: ignore[union-attr]


class TestCanvasFileSystemVisibility(APIBaseTest):
    """The file system only applies project RBAC, so canvas rows follow the channel's visibility on read."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(team_scope(self.team.id))
        self.other = User.objects.create_and_join(self.organization, "other@example.com", "pwd")
        self.public_channel = Channel.objects.create(team=self.team, name="general", created_by=self.user)
        self.personal_channel = Channel.objects.create(
            team=self.team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=self.user
        )
        self.public_canvas = Canvas.objects.create(
            team=self.team, channel=self.public_channel, name="Shared", created_by=self.user
        )
        self.personal_canvas = Canvas.objects.create(
            team=self.team, channel=self.personal_channel, name="Mine", created_by=self.user
        )

    def _refs(self, query: str) -> set[str]:
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/{query}")
        self.assertEqual(response.status_code, 200, response.content)
        return {entry["ref"] for entry in response.json()["results"] if entry["type"] == "canvas"}

    @parameterized.expand(
        [
            ("list", "?type=canvas"),
            ("search", "?search=Mine&type=canvas"),
            ("folder", "?parent=Unfiled/Canvases&depth=3"),
        ]
    )
    def test_personal_canvas_lists_for_its_owner_only(self, _name: str, query: str) -> None:
        self.assertIn(str(self.personal_canvas.id), self._refs(query))

        self.client.force_login(self.other)
        refs = self._refs(query)
        self.assertNotIn(str(self.personal_canvas.id), refs)
        if "search" not in query:
            self.assertIn(str(self.public_canvas.id), refs)

    def test_personal_canvas_stays_out_of_another_members_recents(self) -> None:
        base = f"/api/projects/{self.team.id}/file_system"
        self.client.force_login(self.other)
        self.client.post(
            f"{base}/log_view/",
            {"type": "canvas", "ref": str(self.personal_canvas.id), "viewed_at": "2026-09-01T00:00:00Z"},
        )
        recents = self.client.get(f"{base}/?order_by=-last_viewed_at&limit=5").json()
        self.assertNotIn(str(self.personal_canvas.id), {entry["ref"] for entry in recents["results"]})

    def test_deleting_the_row_soft_deletes_the_canvas_for_someone_who_may_see_it(self) -> None:
        entry = FileSystem.objects.get(team=self.team, type="canvas", ref=str(self.public_canvas.id))
        response = self.client.delete(f"/api/projects/{self.team.id}/file_system/{entry.id}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["deleted"][0]["mode"], "soft")
        self.public_canvas.refresh_from_db()
        self.assertTrue(self.public_canvas.deleted)
        self.assertFalse(FileSystem.objects.filter(id=entry.id).exists())

    def test_a_sandbox_token_does_not_inherit_its_users_private_channels(self) -> None:
        private_channel = Channel.objects.create(
            team=self.team, name="team-private", channel_type=Channel.ChannelType.PRIVATE, created_by=self.other
        )
        private_channel.memberships.create(team=self.team, user=self.user)
        private_canvas = Canvas.objects.create(
            team=self.team, channel=private_channel, name="Private plan", created_by=self.other
        )
        self.assertIn(str(private_canvas.id), self._refs("?type=canvas"))

        application = OAuthApplication.objects.create(
            name="Canvas sandbox",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            user=self.user,
        )
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token=f"pha_canvas_{uuid4().hex}",
            expires=timezone.now() + timedelta(hours=1),
            scope="file_system:read canvas:read",
            scoped_teams=[self.team.id],
            sandbox_task_id=uuid4(),
        )
        sandbox = APIClient()
        sandbox.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token.token}")
        response = sandbox.get(f"/api/projects/{self.team.id}/file_system/?type=canvas")
        self.assertEqual(response.status_code, 200, response.content)
        refs = {entry["ref"] for entry in response.json()["results"]}
        self.assertIn(str(self.public_canvas.id), refs)
        self.assertNotIn(str(private_canvas.id), refs)

        own = FileSystem.objects.get(team=self.team, type="canvas", ref=str(self.public_canvas.id))
        response = sandbox.delete(f"/api/projects/{self.team.id}/file_system/{own.id}/")
        self.assertEqual(response.status_code, 403, response.content)

    def test_another_member_cannot_delete_a_public_canvas_through_the_file_system(self) -> None:
        entry = FileSystem.objects.get(team=self.team, type="canvas", ref=str(self.public_canvas.id))
        self.client.force_login(self.other)
        response = self.client.delete(f"/api/projects/{self.team.id}/file_system/{entry.id}/")
        self.assertEqual(response.status_code, 403, response.content)
        self.public_canvas.refresh_from_db()
        self.assertFalse(self.public_canvas.deleted)

    def test_the_creator_can_undo_a_file_system_delete(self) -> None:
        entry = FileSystem.objects.get(team=self.team, type="canvas", ref=str(self.personal_canvas.id))
        self.client.delete(f"/api/projects/{self.team.id}/file_system/{entry.id}/")
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/undo_delete/",
            {"items": [{"type": "canvas", "ref": str(self.personal_canvas.id), "path": entry.path}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.personal_canvas.refresh_from_db()
        self.assertFalse(self.personal_canvas.deleted)

    def test_restoring_a_hidden_canvas_through_undo_delete_is_refused(self) -> None:
        self.personal_canvas.deleted = True
        self.personal_canvas.save()
        self.client.force_login(self.other)
        response = self.client.post(
            f"/api/projects/{self.team.id}/file_system/undo_delete/",
            {"items": [{"type": "canvas", "ref": str(self.personal_canvas.id), "path": "Unfiled/Canvases/Mine"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.personal_canvas.refresh_from_db()
        self.assertTrue(self.personal_canvas.deleted)

    def test_deleting_a_hidden_canvas_row_is_refused(self) -> None:
        entry = FileSystem.objects.get(team=self.team, type="canvas", ref=str(self.personal_canvas.id))
        self.client.force_login(self.other)
        response = self.client.delete(f"/api/projects/{self.team.id}/file_system/{entry.id}/")
        self.assertIn(response.status_code, (403, 404), response.content)
        self.personal_canvas.refresh_from_db()
        self.assertFalse(self.personal_canvas.deleted)
