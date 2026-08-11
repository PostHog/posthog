from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.scoping import team_scope
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.canvas.backend import activity_visibility, build_service
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.canvas.backend.source import synthetic_source_project
from products.tasks.backend.models import Channel, Task


class InMemoryStorage:
    """A dict-backed stand-in for posthog.storage.object_storage."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def write(self, key, content, extras=None):
        self.objects[key] = content

    def read_bytes(self, key, missing_ok=False):
        return self.objects.get(key)

    def delete_objects(self, keys):
        for key in keys:
            self.objects.pop(key, None)


class CanvasAPIBaseTest(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.storage = InMemoryStorage()
        for attribute in ("write", "read_bytes", "delete_objects"):
            patcher = patch.object(build_service.object_storage, attribute, getattr(self.storage, attribute))
            patcher.start()
            self.addCleanup(patcher.stop)
        enqueue = patch("products.canvas.backend.tasks.process_canvas_build.delay")
        self.enqueue = enqueue.start()
        self.addCleanup(enqueue.stop)
        with team_scope(self.team.id):
            self.channel = Channel.objects.create(team=self.team, name="general", created_by=self.user)

    def _create_canvas(self, **overrides) -> str:
        body = {"name": "My canvas", "channel_id": str(self.channel.id), **overrides}
        response = self.client.post(f"/api/projects/{self.team.id}/canvases/", body, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return cast(str, response.json()["id"])

    def _project(self, code: str = "export default function C() { return null }", **overrides) -> dict[str, Any]:
        project = synthetic_source_project(code)
        project.update(overrides)
        return project

    def _publish(self, canvas_id: str, project: dict | None = None, **payload):
        return self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/publish/",
            {"project": project or self._project(), **payload},
            format="json",
        )

    def _activity(self, activity: str) -> list[ActivityLog]:
        return list(
            ActivityLog.objects.filter(team_id=self.team.id, scope="Canvas", activity=activity).order_by("created_at")
        )

    def _changes(self, entry: ActivityLog) -> list[dict[str, Any]]:
        assert entry.detail is not None
        return entry.detail["changes"]

    def _sandbox_client(self, task_id) -> APIClient:
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
            scope="canvas:read canvas:write task:read",
            scoped_teams=[self.team.id],
            sandbox_task_id=task_id,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token.token}")
        return client


class TestCanvasCrud(CanvasAPIBaseTest):
    def test_missing_user_only_sees_public_channels(self):
        with team_scope(self.team.id):
            public = Channel.objects.create(team=self.team, name="public")
            personal = Channel.objects.create(
                team=self.team,
                name="me",
                channel_type=Channel.ChannelType.PERSONAL,
                created_by=None,
            )
            deleted = Channel.objects.create(team=self.team, name="deleted", deleted=True)
            unknown = Channel.objects.create(team=self.team, name="unknown", channel_type="unknown")
            visible_ids = set(Channel.objects.filter(Channel.visible_to_q(None)).values_list("id", flat=True))

        assert public.id in visible_ids
        assert personal.id not in visible_ids
        assert deleted.id not in visible_ids
        assert unknown.id not in visible_ids

    def test_create_lists_and_filters_by_channel(self):
        canvas_id = self._create_canvas()
        with team_scope(self.team.id):
            other_channel = Channel.objects.create(team=self.team, name="other")
        other_id = self._create_canvas(name="Other", channel_id=str(other_channel.id))

        response = self.client.get(f"/api/projects/{self.team.id}/canvases/?channel={self.channel.id}")
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == [canvas_id]

        response = self.client.get(f"/api/projects/{self.team.id}/canvases/")
        assert {row["id"] for row in response.json()["results"]} == {canvas_id, other_id}

    def test_personal_channel_canvases_are_invisible_to_other_users(self):
        # A canvas filed into a teammate's personal channel is private to them:
        # list omits it, and every detail/write action 404s for anyone else.
        private_channel_id = None
        public_canvas_id = self._create_canvas(name="Public canvas")
        with team_scope(self.team.id):
            private_channel = Channel.objects.create(
                team=self.team,
                name="me",
                channel_type=Channel.ChannelType.PERSONAL,
                created_by=self.user,
            )
            private_channel_id = str(private_channel.id)
            private_canvas = Canvas.objects.create(
                team_id=self.team.id,
                channel=private_channel,
                name="Private canvas",
                created_by=self.user,
            )
            private_canvas_id = str(private_canvas.id)

        # The owner sees it in list and can read/write it.
        response = self.client.get(f"/api/projects/{self.team.id}/canvases/")
        ids = {row["id"] for row in response.json()["results"]}
        assert {public_canvas_id, private_canvas_id} <= ids
        assert self.client.get(f"/api/projects/{self.team.id}/canvases/{private_canvas_id}/").status_code == 200
        assert self.client.get(f"/api/projects/{self.team.id}/canvases/{private_canvas_id}/source/").status_code == 200

        # A different user on the same team does not.
        other_user = self._create_user("teammate@example.com")
        self.client.force_login(other_user)

        response = self.client.get(f"/api/projects/{self.team.id}/canvases/")
        ids = {row["id"] for row in response.json()["results"]}
        assert private_canvas_id not in ids
        assert public_canvas_id in ids

        # Filtering by the personal channel id must not leak it either.
        response = self.client.get(f"/api/projects/{self.team.id}/canvases/?channel={private_channel_id}")
        assert response.json()["results"] == []

        base = f"/api/projects/{self.team.id}/canvases/{private_canvas_id}"
        assert self.client.get(f"{base}/").status_code == 404
        assert self.client.get(f"{base}/source/").status_code == 404
        assert self.client.get(f"{base}/versions/").status_code == 404
        assert self.client.get(f"{base}/builds/").status_code == 404
        assert self.client.patch(f"{base}/", {"name": "Renamed"}, format="json").status_code == 404
        assert self.client.post(f"{base}/publish/", {"project": self._project()}, format="json").status_code == 404
        assert self.client.delete(f"{base}/").status_code == 404

    def test_task_bound_sandbox_can_create_only_for_its_bound_task(self):
        bound_task = Task.objects.create(
            team=self.team,
            channel=self.channel,
            created_by=self.user,
            title="Bound",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        other_task = Task.objects.create(
            team=self.team,
            channel=self.channel,
            created_by=self.user,
            title="Other",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        client = self._sandbox_client(bound_task.id)
        url = f"/api/projects/{self.team.id}/canvases/"

        allowed = client.post(
            url,
            {"name": "Bound canvas", "channel_id": str(self.channel.id)},
            format="json",
            HTTP_X_POSTHOG_TASK_ID=str(bound_task.id),
        )
        denied = client.post(
            url,
            {"name": "Other canvas", "channel_id": str(self.channel.id)},
            format="json",
            HTTP_X_POSTHOG_TASK_ID=str(other_task.id),
        )

        assert allowed.status_code == status.HTTP_201_CREATED
        assert Canvas.objects.unscoped().get(id=allowed.json()["id"]).generation_task_id == bound_task.id
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_task_bound_sandbox_can_read_only_its_canvases(self):
        bound_task = Task.objects.create(
            team=self.team,
            channel=self.channel,
            created_by=self.user,
            title="Bound",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        other_task = Task.objects.create(
            team=self.team,
            channel=self.channel,
            created_by=self.user,
            title="Other",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        own_canvas = Canvas.objects.unscoped().create(
            team=self.team,
            channel=self.channel,
            name="Own",
            generation_task_id=bound_task.id,
        )
        other_canvas = Canvas.objects.unscoped().create(
            team=self.team,
            channel=self.channel,
            name="Other",
            generation_task_id=other_task.id,
        )
        client = self._sandbox_client(bound_task.id)

        listing = client.get(
            f"/api/projects/{self.team.id}/canvases/",
            HTTP_X_POSTHOG_TASK_ID=str(bound_task.id),
        )
        other_detail = client.get(
            f"/api/projects/{self.team.id}/canvases/{other_canvas.id}/",
            HTTP_X_POSTHOG_TASK_ID=str(bound_task.id),
        )

        assert [row["id"] for row in listing.json()["results"]] == [str(own_canvas.id)]
        assert other_detail.status_code == status.HTTP_404_NOT_FOUND

    def test_create_rejects_unknown_channel(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/",
            {"name": "Bad", "channel_id": str(uuid4())},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_partial_update_metadata(self):
        canvas_id = self._create_canvas()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/",
            {"name": "Renamed", "context": "notes", "pinned": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["name"] == "Renamed"
        assert body["context"] == "notes"
        assert body["pinned"] is True

        response = self.client.patch(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/", {"pinned": False}, format="json"
        )
        assert response.json()["pinned"] is False

    def test_generation_task_pointer_validates_team(self):
        canvas_id = self._create_canvas()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/",
            {"generation_task_id": str(uuid4())},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        response = self.client.patch(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/",
            {"generation_task_id": None},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

    def test_destroy_soft_deletes(self):
        canvas_id = self._create_canvas()
        response = self.client.delete(f"/api/projects/{self.team.id}/canvases/{canvas_id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/").status_code == 404
        assert Canvas.objects.unscoped().filter(id=canvas_id, deleted=True).exists()


class TestCanvasSourceAndPublish(CanvasAPIBaseTest):
    def test_source_of_unpublished_canvas_is_synthetic_and_blank(self):
        canvas_id = self._create_canvas()
        response = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/source/")
        body = response.json()
        assert body["current_version_id"] is None
        assert body["project"]["files"]["src/canvas.tsx"] == ""

    def test_publish_creates_version_and_build_and_round_trips_source(self):
        canvas_id = self._create_canvas()
        project = self._project()
        project["files"]["src/extra.ts"] = "export const x = 1"

        with self.captureOnCommitCallbacks(execute=True):
            response = self._publish(canvas_id, project, prompt="first build", expected_current_version_id=None)
        assert response.status_code == status.HTTP_200_OK, response.json()
        version_id = response.json()["current_version_id"]

        canvas = Canvas.objects.unscoped().get(id=canvas_id)
        assert str(canvas.current_source_version_id) == version_id
        build = CanvasBuild.objects.unscoped().get(canvas_id=canvas_id)
        assert build.status == CanvasBuild.STATUS_QUEUED
        self.enqueue.assert_called_once_with(self.team.id, str(build.id))

        # The multi-file project round-trips from the stored version.
        response = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/source/")
        body = response.json()
        assert body["current_version_id"] == version_id
        assert body["project"]["files"]["src/extra.ts"] == "export const x = 1"

    def test_public_members_can_publish_current_source_but_cannot_edit(self):
        canvas_id = self._create_canvas()
        first = self._publish(canvas_id, expected_current_version_id=None)
        assert first.status_code == status.HTTP_200_OK
        version_id = first.json()["current_version_id"]
        other_user = self._create_user("canvas-member@example.com")
        self.client.force_login(other_user)
        base = f"/api/projects/{self.team.id}/canvases/{canvas_id}"

        metadata_edit = self.client.patch(f"{base}/", {"name": "Changed"}, format="json")
        source_edit = self.client.post(
            f"{base}/edit/",
            {
                "operations": [{"path": "src/canvas.tsx", "content": "export default function C() { return 2 }"}],
                "expected_current_version_id": version_id,
            },
            format="json",
        )
        source_publish = self.client.post(
            f"{base}/publish/",
            {
                "project": self._project("export default function C() { return 2 }"),
                "expected_current_version_id": version_id,
            },
            format="json",
        )
        current_version_publish = self.client.post(
            f"{base}/publish-current-version/",
            {"expected_current_version_id": version_id},
            format="json",
        )

        assert metadata_edit.status_code == status.HTTP_404_NOT_FOUND
        assert source_edit.status_code == status.HTTP_404_NOT_FOUND
        assert source_publish.status_code == status.HTTP_404_NOT_FOUND
        assert current_version_publish.status_code == status.HTTP_200_OK, current_version_publish.json()
        assert current_version_publish.json()["source_version_id"] == version_id
        assert str(Canvas.objects.unscoped().get(id=canvas_id).current_source_version_id) == version_id

    def test_stale_guard_conflicts(self):
        canvas_id = self._create_canvas()
        first = self._publish(canvas_id, expected_current_version_id=None)
        assert first.status_code == status.HTTP_200_OK

        response = self._publish(
            canvas_id,
            self._project("export default function C() { return 2 }"),
            expected_current_version_id=None,
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        body = response.json()
        assert body["code"] == "version_conflict"
        assert body["current_version_id"] == first.json()["current_version_id"]
        assert len(self.storage.objects) == 1

    def test_validation_errors_reject_publish(self):
        canvas_id = self._create_canvas()
        response = self._publish(canvas_id, self._project('import x from "left-pad"'))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        codes = {d["code"] for d in response.json()["diagnostics"]}
        assert "import_not_allowed" in codes
        assert not CanvasSourceVersion.objects.unscoped().filter(canvas_id=canvas_id).exists()

    def test_undeclared_capabilities_reject_publish(self):
        canvas_id = self._create_canvas()
        response = self._publish(canvas_id, self._project('const r = ph.loadInsight("abc123")'))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        codes = {d["code"] for d in response.json()["diagnostics"]}
        assert "capability_missing_insight" in codes

        declared = self._project('const r = ph.loadInsight("abc123")')
        declared["capabilities"] = {
            "posthog": {"insights": ["abc123"], "inlineQueries": False, "captureEvents": []},
            "network": {"origins": []},
        }
        response = self._publish(canvas_id, declared, expected_current_version_id=None)
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_publish_supersedes_older_queued_build(self):
        canvas_id = self._create_canvas()
        first = self._publish(canvas_id, expected_current_version_id=None)
        second = self._publish(
            canvas_id,
            self._project("export default function C() { return 2 }"),
            expected_current_version_id=first.json()["current_version_id"],
        )
        assert second.status_code == status.HTTP_200_OK

        statuses = list(
            CanvasBuild.objects.unscoped()
            .filter(canvas_id=canvas_id)
            .order_by("created_at")
            .values_list("status", flat=True)
        )
        assert statuses == [CanvasBuild.STATUS_FAILED, CanvasBuild.STATUS_QUEUED]

    def test_publish_capacity_cap_returns_429(self):
        canvas_id = self._create_canvas()
        with patch.object(build_service, "MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM", 0):
            response = self._publish(canvas_id, expected_current_version_id=None)
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert not CanvasSourceVersion.objects.unscoped().filter(canvas_id=canvas_id).exists()
        assert self.storage.objects == {}

    def test_edit_applies_operations_to_stored_head(self):
        canvas_id = self._create_canvas()
        first = self._publish(canvas_id, expected_current_version_id=None)
        version_id = first.json()["current_version_id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/edit/",
            {
                "operations": [{"path": "src/added.ts", "content": "export {}"}],
                "expected_current_version_id": version_id,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        source = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/source/").json()
        assert source["project"]["files"]["src/added.ts"] == "export {}"
        # The original component survives the per-file edit.
        assert "src/canvas.tsx" in source["project"]["files"]

    def test_edit_delete_of_missing_file_400s(self):
        canvas_id = self._create_canvas()
        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/edit/",
            {
                "operations": [{"path": "src/nope.ts", "content": None}],
                "expected_current_version_id": None,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["diagnostics"][0]["code"] == "edit_target_missing"

    def test_publish_clears_legacy_code(self):
        canvas_id = self._create_canvas()
        Canvas.objects.unscoped().filter(id=canvas_id).update(legacy_code="export default () => null")

        source = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/source/").json()
        assert source["project"]["files"]["src/canvas.tsx"] == "export default () => null"

        response = self._publish(canvas_id, expected_current_version_id=None)
        assert response.status_code == status.HTTP_200_OK
        assert Canvas.objects.unscoped().get(id=canvas_id).legacy_code is None


class TestCanvasRevertAndBuilds(CanvasAPIBaseTest):
    def _published_canvas(self) -> tuple[str, str, str]:
        canvas_id = self._create_canvas()
        first = self._publish(canvas_id, expected_current_version_id=None)
        second = self._publish(
            canvas_id,
            self._project("export default function C() { return 2 }"),
            expected_current_version_id=first.json()["current_version_id"],
        )
        return canvas_id, first.json()["current_version_id"], second.json()["current_version_id"]

    def test_revert_moves_head_and_queues_build(self):
        canvas_id, v1, v2 = self._published_canvas()
        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/revert/",
            {"version_id": v1, "expected_current_version_id": v2},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["source_version_id"] == v1
        assert str(Canvas.objects.unscoped().get(id=canvas_id).current_source_version_id) == v1

    def test_versions_history_and_versioned_source(self):
        canvas_id, v1, v2 = self._published_canvas()
        versions = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/versions/").json()["results"]
        assert [v["id"] for v in versions] == [v2, v1]
        assert versions[1]["parent_version_id"] is None

        old = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/source/?version_id={v1}").json()
        assert "return null" in old["project"]["files"]["src/canvas.tsx"]
        # The head pointer is reported regardless of which version was read.
        assert old["current_version_id"] == v2

        response = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/source/?version_id={uuid4()}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_revert_rejects_foreign_version(self):
        canvas_id, _, v2 = self._published_canvas()
        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/revert/",
            {"version_id": str(uuid4()), "expected_current_version_id": v2},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_builds_lifecycle_includes_published_build_beyond_window(self):
        canvas_id, v1, v2 = self._published_canvas()
        canvas = Canvas.objects.unscoped().get(id=canvas_id)
        published = CanvasBuild.objects.unscoped().filter(canvas_id=canvas_id, status="queued").first()
        assert published is not None
        published.status = CanvasBuild.STATUS_READY
        published.save()
        canvas.published_build = published
        canvas.save()

        # Bury the published build past the window with newer failed builds.
        version = CanvasSourceVersion.objects.unscoped().get(id=v2)
        with team_scope(self.team.id):
            for _ in range(25):
                CanvasBuild.objects.create(
                    team_id=self.team.id,
                    canvas_id=canvas_id,
                    source_version=version,
                    status=CanvasBuild.STATUS_FAILED,
                )

        response = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/builds/")
        body = response.json()
        assert body["published_build_id"] == str(published.id)
        assert str(published.id) in {build["id"] for build in body["builds"]}

    def test_builds_lifecycle_includes_requested_historical_build_beyond_window(self):
        canvas_id, v1, v2 = self._published_canvas()
        historical = CanvasBuild.objects.unscoped().get(canvas_id=canvas_id, source_version_id=v1)
        historical.status = CanvasBuild.STATUS_READY
        historical.save(update_fields=["status"])
        version = CanvasSourceVersion.objects.unscoped().get(id=v2)
        with team_scope(self.team.id):
            for _ in range(25):
                CanvasBuild.objects.create(
                    team_id=self.team.id,
                    canvas_id=canvas_id,
                    source_version=version,
                    status=CanvasBuild.STATUS_FAILED,
                )

        response = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/builds/?version_id={v1}")

        assert response.status_code == status.HTTP_200_OK
        assert str(historical.id) in {build["id"] for build in response.json()["builds"]}

    def test_build_with_pruned_artifacts_advertises_no_url(self):
        canvas_id, v1, _ = self._published_canvas()
        build = CanvasBuild.objects.unscoped().filter(canvas_id=canvas_id).first()
        assert build is not None
        build.status = CanvasBuild.STATUS_READY
        build.manifest = {
            "entryHtml": "index.html",
            "assets": [],
            "dependencies": {},
            "canvasSdkVersion": "0.1.0",
            "capabilities": {},
        }
        build.artifact_object_prefix = None  # retention pruned the objects
        build.save()

        response = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/builds/")
        record = next(b for b in response.json()["builds"] if b["id"] == str(build.id))
        assert record["build_status"] == "ready"
        assert record["artifact_url"] is None

    def test_build_actions(self):
        canvas_id, *_ = self._published_canvas()
        build = CanvasBuild.objects.unscoped().filter(canvas_id=canvas_id, status="queued").first()
        assert build is not None

        def act(action: str, build_id=None):
            return self.client.post(
                f"/api/projects/{self.team.id}/canvases/{canvas_id}/builds/action/",
                {"action": action, "build_id": str(build_id or build.id)},
                format="json",
            )

        assert act("pin").json()["pinned"] is True
        assert act("unpin").json()["pinned"] is False

        with patch.object(build_service, "MAX_PINNED_BUILDS_PER_CANVAS", 1):
            assert act("pin").status_code == status.HTTP_200_OK
            with team_scope(self.team.id):
                other = CanvasBuild.objects.create(
                    team_id=self.team.id,
                    canvas_id=canvas_id,
                    source_version_id=build.source_version_id,
                    status=CanvasBuild.STATUS_QUEUED,
                )
            assert act("pin", other.id).status_code == status.HTTP_400_BAD_REQUEST
            assert act("unpin").status_code == status.HTTP_200_OK

        # Cancel the queued build, then retry it.
        response = act("cancel")
        assert response.json()["build_status"] == "failed"
        response = act("retry")
        assert response.json()["build_status"] == "queued"

        # Retry of a non-failed build is rejected.
        assert act("retry").status_code == status.HTTP_400_BAD_REQUEST

        # Retry respects the capacity cap.
        act("cancel")
        with patch.object(build_service, "MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM", 0):
            assert act("retry").status_code == status.HTTP_429_TOO_MANY_REQUESTS


class TestCanvasActivityLog(CanvasAPIBaseTest):
    def test_publish_snapshots_capabilities_and_logs_the_diff(self):
        canvas_id = self._create_canvas()
        first = self._publish(canvas_id, expected_current_version_id=None)
        assert first.status_code == status.HTTP_200_OK, first.json()

        default_capabilities = {
            "posthog": {"insights": [], "inlineQueries": False, "captureEvents": []},
            "network": {"origins": []},
        }
        widened_capabilities = {
            "posthog": {"insights": ["abc123"], "inlineQueries": True, "captureEvents": []},
            "network": {"origins": []},
        }
        widened = self._project("export default function C() { return 2 }")
        widened["capabilities"] = widened_capabilities
        second = self._publish(canvas_id, widened, expected_current_version_id=first.json()["current_version_id"])
        assert second.status_code == status.HTTP_200_OK, second.json()

        versions = CanvasSourceVersion.objects.unscoped().filter(canvas_id=canvas_id).order_by("created_at")
        assert [version.capabilities for version in versions] == [default_capabilities, widened_capabilities]

        entries = self._activity("published")
        assert len(entries) == 2
        assert entries[0].user == self.user
        changes = self._changes(entries[1])
        assert len(changes) == 1
        assert changes[0]["field"] == "capabilities"
        assert changes[0]["before"] == default_capabilities
        assert changes[0]["after"] == widened_capabilities

    def test_revert_logs_the_head_move(self):
        canvas_id = self._create_canvas()
        first = self._publish(canvas_id, expected_current_version_id=None)
        v1 = first.json()["current_version_id"]
        second = self._publish(
            canvas_id,
            self._project("export default function C() { return 2 }"),
            expected_current_version_id=v1,
        )
        v2 = second.json()["current_version_id"]
        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/revert/",
            {"version_id": v1, "expected_current_version_id": v2},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        entries = self._activity("reverted")
        assert len(entries) == 1
        changes = self._changes(entries[0])
        assert changes[0]["field"] == "current_source_version"
        assert changes[0]["before"] == v2
        assert changes[0]["after"] == v1

    def test_rename_logs_a_change_but_a_no_op_update_does_not(self):
        canvas_id = self._create_canvas()
        base = f"/api/projects/{self.team.id}/canvases/{canvas_id}"

        response = self.client.patch(f"{base}/", {"name": "Renamed"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        entries = self._activity("updated")
        assert len(entries) == 1
        assert self._changes(entries[0]) == [
            {"type": "Canvas", "action": "changed", "field": "name", "before": "My canvas", "after": "Renamed"}
        ]

        response = self.client.patch(f"{base}/", {"name": "Renamed"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert len(self._activity("updated")) == 1


class TestCanvasActivityVisibility(CanvasAPIBaseTest):
    """Personal-channel canvases are owner-only, so their team-scoped activity rows must
    not leak to other members through the team- or org-wide activity feed."""

    def _personal_canvas(self, owner) -> Canvas:
        with team_scope(self.team.id):
            channel = Channel.objects.create(
                team=self.team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=owner
            )
            return Canvas.objects.create(team_id=self.team.id, channel=channel, name="Private", created_by=owner)

    def test_team_visible_ids_include_public_but_hide_others_personal_canvas(self):
        other = self._create_user("teammate-vis@example.com")
        private = self._personal_canvas(self.user)
        public_id = self._create_canvas(name="Public")

        owner_visible = activity_visibility.visible_canvas_ids(self.team.id, self.user)
        other_visible = activity_visibility.visible_canvas_ids(self.team.id, other)

        assert {public_id, str(private.id)} <= owner_visible
        assert public_id in other_visible
        assert str(private.id) not in other_visible

    def test_org_hidden_ids_exclude_owner_but_include_other_members(self):
        other = self._create_user("teammate-org@example.com")
        private = self._personal_canvas(self.user)

        assert str(private.id) not in activity_visibility.hidden_personal_canvas_ids_for_org(
            self.organization.id, self.user
        )
        assert str(private.id) in activity_visibility.hidden_personal_canvas_ids_for_org(self.organization.id, other)


class TestCanvasDraftBuilds(CanvasAPIBaseTest):
    def _draft(self, canvas_id: str, project: dict | None = None, **payload):
        return self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/draft/",
            {"project": project or self._project(), **payload},
            format="json",
        )

    def _promote(self, canvas_id: str, version_id: str, expected: str | None):
        return self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/promote/",
            {"version_id": version_id, "expected_current_version_id": expected},
            format="json",
        )

    def _published_canvas(self) -> tuple[str, str]:
        canvas_id = self._create_canvas()
        response = self._publish(canvas_id, expected_current_version_id=None)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return canvas_id, response.json()["current_version_id"]

    def test_draft_stages_version_and_build_without_moving_head(self):
        canvas_id, head_id = self._published_canvas()

        response = self._draft(canvas_id, self._project("export default function C() { return 2 }"))
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["version_id"] != head_id
        assert body["build"]["build_status"] == "queued"

        builds = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/builds/").json()
        assert builds["current_version_id"] == head_id

        # A draft stays out of the published-history timeline (undo/revert), so
        # only the head shows there and the draft is not revertable onto.
        version_ids = [
            row["id"]
            for row in self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/versions/").json()["results"]
        ]
        assert version_ids == [head_id]

    def test_drafts_endpoint_lists_drafts_with_build_status(self):
        canvas_id, head_id = self._published_canvas()
        draft_body = self._draft(canvas_id, self._project("export default function C() { return 2 }")).json()

        drafts = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/drafts/").json()
        assert [row["version_id"] for row in drafts] == [draft_body["version_id"]]
        assert drafts[0]["build_status"] == "queued"
        assert drafts[0]["build_id"] == draft_body["build"]["id"]

    def test_draft_is_not_revertable(self):
        canvas_id, head_id = self._published_canvas()
        draft_version_id = self._draft(canvas_id).json()["version_id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/revert/",
            {"version_id": draft_version_id, "expected_current_version_id": head_id},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_draft_reports_capability_widening_over_head(self):
        canvas_id, head_id = self._published_canvas()

        widened = self._project("export default function C() { return 2 }")
        widened["capabilities"] = {
            "posthog": {"insights": ["abc123"], "inlineQueries": True, "captureEvents": []},
            "network": {"origins": []},
        }
        response = self._draft(canvas_id, widened)
        widening = response.json()["capability_widening"]
        assert widening["widens"] is True
        assert widening["insights_added"] == ["abc123"]
        assert widening["inline_queries_enabled"] is True

        entries = self._activity("drafted")
        assert len(entries) == 1
        changes = self._changes(entries[0])
        assert changes[0]["field"] == "capabilities"

        unchanged = self._draft(canvas_id, self._project("export default function C() { return 3 }"))
        assert unchanged.json()["capability_widening"]["widens"] is False

    def test_promote_reuses_ready_build_and_moves_head(self):
        canvas_id, head_id = self._published_canvas()
        draft_body = self._draft(canvas_id, self._project("export default function C() { return 2 }")).json()
        draft_version_id = draft_body["version_id"]
        CanvasBuild.objects.for_team(self.team.id).filter(id=draft_body["build"]["id"]).update(
            status=CanvasBuild.STATUS_READY,
            artifact_object_prefix="canvas_artifact/test",
            finished_at=timezone.now(),
        )
        enqueued_before = self.enqueue.call_count

        response = self._promote(canvas_id, draft_version_id, expected=head_id)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == draft_body["build"]["id"]
        assert response.json()["build_status"] == "ready"
        assert self.enqueue.call_count == enqueued_before

        builds = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/builds/").json()
        assert builds["current_version_id"] == draft_version_id
        assert builds["published_build_id"] == draft_body["build"]["id"]
        versions = {
            row["id"]: row
            for row in self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/versions/").json()["results"]
        }
        assert versions[draft_version_id]["draft"] is False
        assert len(self._activity("published")) == 2

    def test_promote_rebuilds_when_artifacts_pruned(self):
        canvas_id, head_id = self._published_canvas()
        draft_body = self._draft(canvas_id).json()
        CanvasBuild.objects.for_team(self.team.id).filter(id=draft_body["build"]["id"]).update(
            status=CanvasBuild.STATUS_READY, artifact_object_prefix=None, finished_at=timezone.now()
        )

        response = self._promote(canvas_id, draft_body["version_id"], expected=head_id)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] != draft_body["build"]["id"]
        assert response.json()["build_status"] == "queued"

    def test_promote_adopts_in_flight_build_without_requeuing(self):
        # Promoting while the draft's build is still running must adopt that
        # build, not queue a duplicate of the same version — _finalize_ready
        # advances the live pointer once it completes, now that the version is
        # the head.
        canvas_id, head_id = self._published_canvas()
        draft_body = self._draft(canvas_id).json()
        CanvasBuild.objects.for_team(self.team.id).filter(id=draft_body["build"]["id"]).update(
            status=CanvasBuild.STATUS_BUILDING
        )
        published_before = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/builds/").json()[
            "published_build_id"
        ]
        enqueued_before = self.enqueue.call_count

        response = self._promote(canvas_id, draft_body["version_id"], expected=head_id)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == draft_body["build"]["id"]
        assert response.json()["build_status"] == "building"
        assert self.enqueue.call_count == enqueued_before
        assert (
            CanvasBuild.objects.for_team(self.team.id).filter(source_version_id=draft_body["version_id"]).count() == 1
        )

        builds = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/builds/").json()
        assert builds["current_version_id"] == draft_body["version_id"]
        # The live artifact does not move until the adopted build finalizes.
        assert builds["published_build_id"] == published_before

    def test_draft_rejects_at_capacity_before_uploading(self):
        canvas_id, _ = self._published_canvas()
        objects_before = set(self.storage.objects)

        with patch.object(build_service, "MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM", 0):
            response = self._draft(canvas_id, self._project("export default function C() { return 3 }"))

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert set(self.storage.objects) == objects_before

    def test_promote_rejects_stale_guard_and_non_draft_versions(self):
        canvas_id, head_id = self._published_canvas()
        draft_version_id = self._draft(canvas_id).json()["version_id"]

        stale = self._promote(canvas_id, draft_version_id, expected=str(uuid4()))
        assert stale.status_code == status.HTTP_409_CONFLICT

        not_a_draft = self._promote(canvas_id, head_id, expected=head_id)
        assert not_a_draft.status_code == status.HTTP_404_NOT_FOUND

        builds = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/builds/").json()
        assert builds["current_version_id"] == head_id
