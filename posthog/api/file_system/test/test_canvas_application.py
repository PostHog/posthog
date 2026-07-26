import gzip
import json
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from posthog.models.file_system.canvas import CanvasApplication, CanvasBuild, CanvasSourceVersion
from posthog.models.file_system.file_system import FileSystem
from posthog.tasks.canvas_builds import _complete_build, _fail_build, collect_canvas_objects

from products.tasks.backend.facade import api as tasks_api


def source_project(label: str = "hello") -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "files": {
            "index.html": '<div id="root"></div><script type="module" src="/src/main.ts"></script>',
            "src/main.ts": f'document.querySelector("#root")!.textContent = "{label}"',
        },
        "entryHtml": "index.html",
        "dependencies": {},
        "canvasSdkVersion": "1.0.0",
        "capabilities": {
            "posthog": {"insights": [], "inlineQueries": False, "captureEvents": []},
            "network": {"origins": []},
        },
    }


class TestCanvasApplicationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        response = self.client.post(
            f"/api/projects/{self.team.id}/desktop_file_system/",
            {"path": "Channel/Canvas", "type": "dashboard", "meta": {"kind": "freeform"}},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.canvas_id = UUID(cast(str, response.json()["id"]))
        self.task_id = tasks_api.create_task_without_run(
            team=self.team,
            user_id=self.user.id,
            origin_product=tasks_api.TaskOriginProduct.USER_CREATED,
            title="Canvas task",
        )
        self.task_run_id = tasks_api.create_run(self.task_id).id
        self.objects: dict[str, bytes] = {}

    def source_url(self) -> str:
        return f"/api/projects/{self.team.id}/desktop_file_system/{self.canvas_id}/canvas/source/"

    def history_url(self) -> str:
        return f"/api/projects/{self.team.id}/desktop_file_system/{self.canvas_id}/canvas/history/"

    def publish_payload(self, label: str = "hello", expected: str | None = None) -> dict[str, Any]:
        return {
            "project": source_project(label),
            "expectedCurrentVersionId": expected,
            "taskId": str(self.task_id),
            "taskRunId": str(self.task_run_id),
            "prompt": f"Build {label}",
        }

    def object_write(self, key: str, content: bytes, **kwargs: Any) -> None:
        self.objects[key] = content

    def object_read(self, key: str, **kwargs: Any) -> bytes | None:
        return self.objects.get(key)

    @patch("posthog.api.file_system.canvas_application.build_canvas.delay")
    @patch("posthog.models.file_system.canvas.object_storage.read_bytes")
    @patch("posthog.models.file_system.canvas.object_storage.write")
    def test_publish_persists_private_source_and_queues_build(self, write: Any, read: Any, delay: Any) -> None:
        write.side_effect = self.object_write
        read.side_effect = self.object_read

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.source_url(), self.publish_payload())

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        body = response.json()
        self.assertEqual(body["version"]["taskId"], str(self.task_id))
        self.assertEqual(body["version"]["taskRunId"], str(self.task_run_id))
        self.assertEqual(body["version"]["parentVersionId"], None)
        self.assertEqual(body["build"]["status"], "queued")
        self.assertNotIn("project", body["version"])

        version = CanvasSourceVersion.objects.for_team(self.team.id).get(id=body["version"]["id"])
        self.assertTrue(version.source_object_key.startswith(f"canvas/source/{self.team.id}/sha256/"))
        archive = gzip.decompress(self.objects[version.source_object_key])
        self.assertEqual(json.loads(archive), source_project())
        delay.assert_called_once_with(str(body["build"]["id"]), self.team.id)

        current = self.client.get(self.source_url())
        self.assertEqual(current.status_code, status.HTTP_200_OK, current.json())
        self.assertEqual(current.json()["project"], source_project())
        self.assertEqual(current.json()["version"], body["version"])

    @patch("posthog.api.file_system.canvas_application.build_canvas.delay")
    @patch("posthog.models.file_system.canvas.object_storage.read_bytes")
    @patch("posthog.models.file_system.canvas.object_storage.write")
    def test_stale_publish_cannot_advance_source_history(self, write: Any, read: Any, delay: Any) -> None:
        write.side_effect = self.object_write
        read.side_effect = self.object_read
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(self.source_url(), self.publish_payload())
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second_run = tasks_api.create_run(self.task_id)
        payload = self.publish_payload("stale", expected="00000000-0000-0000-0000-000000000000")
        payload["taskRunId"] = str(second_run.id)
        response = self.client.post(self.source_url(), payload)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.json())
        self.assertEqual(response.json()["code"], "version_conflict")
        self.assertEqual(response.json()["currentVersionId"], first.json()["version"]["id"])
        self.assertEqual(CanvasSourceVersion.objects.for_team(self.team.id).count(), 1)

    @patch("posthog.api.file_system.canvas_application.build_canvas.delay")
    @patch("posthog.models.file_system.canvas.object_storage.read_bytes")
    @patch("posthog.models.file_system.canvas.object_storage.write")
    def test_patch_publishes_a_diff_without_replacing_untouched_files(self, write: Any, read: Any, delay: Any) -> None:
        write.side_effect = self.object_write
        read.side_effect = self.object_read
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(self.source_url(), self.publish_payload())
        next_run = tasks_api.create_run(self.task_id)

        with self.captureOnCommitCallbacks(execute=True):
            patched = self.client.patch(
                self.source_url(),
                {
                    "patch": {
                        "upsertFiles": {"src/main.ts": 'document.body.textContent = "patched"'},
                        "deleteFiles": [],
                        "upsertAssets": {},
                        "deleteAssets": [],
                    },
                    "expectedCurrentVersionId": first.json()["version"]["id"],
                    "taskId": str(self.task_id),
                    "taskRunId": str(next_run.id),
                },
                format="json",
            )

        self.assertEqual(patched.status_code, status.HTTP_201_CREATED, patched.json())
        current = self.client.get(self.source_url()).json()["project"]
        self.assertEqual(current["files"]["src/main.ts"], 'document.body.textContent = "patched"')
        self.assertIn("index.html", current["files"])

    @patch("posthog.api.file_system.canvas_application.build_canvas.delay")
    @patch("posthog.models.file_system.canvas.object_storage.read_bytes")
    @patch("posthog.models.file_system.canvas.object_storage.write")
    def test_history_is_normalized_and_scoped_to_canvas(self, write: Any, read: Any, delay: Any) -> None:
        write.side_effect = self.object_write
        read.side_effect = self.object_read
        with self.captureOnCommitCallbacks(execute=True):
            published = self.client.post(self.source_url(), self.publish_payload())
        self.assertEqual(published.status_code, status.HTTP_201_CREATED)

        history = self.client.get(self.history_url())
        self.assertEqual(history.status_code, status.HTTP_200_OK, history.json())
        self.assertEqual(history.json()["currentSourceVersionId"], published.json()["version"]["id"])
        self.assertEqual(history.json()["activeBuildId"], None)
        self.assertEqual(history.json()["versions"], [published.json()["version"]])
        self.assertEqual(history.json()["builds"], [published.json()["build"]])

    def test_publish_requires_matching_task_run_provenance(self) -> None:
        other_task_id = tasks_api.create_task_without_run(
            team=self.team,
            user_id=self.user.id,
            origin_product=tasks_api.TaskOriginProduct.USER_CREATED,
            title="Other",
        )
        other_run = tasks_api.create_run(other_task_id)
        payload = self.publish_payload()
        payload["taskRunId"] = str(other_run.id)

        response = self.client.post(self.source_url(), payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertEqual(CanvasSourceVersion.objects.for_team(self.team.id).count(), 0)

    @patch("posthog.api.file_system.file_system.FileSystemViewSet._is_sandbox_authenticated", return_value=True)
    @patch("posthog.api.file_system.canvas_application.build_canvas.delay")
    @patch("posthog.models.file_system.canvas.object_storage.write")
    def test_sandbox_publish_derives_task_and_run_attribution(
        self, write: Any, delay: Any, sandbox_authenticated: Any
    ) -> None:
        payload = self.publish_payload()
        payload.pop("taskId")
        payload.pop("taskRunId")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.source_url(),
                payload,
                HTTP_X_POSTHOG_TASK_ID=str(self.task_id),
                HTTP_X_POSTHOG_TASK_RUN_ID=str(self.task_run_id),
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["version"]["taskId"], str(self.task_id))
        self.assertEqual(response.json()["version"]["taskRunId"], str(self.task_run_id))
        sandbox_authenticated.assert_called()

    def test_canvas_source_is_not_visible_through_another_team(self) -> None:
        other_team = self.organization.teams.create(name="Other team")
        other_canvas = FileSystem.objects.create(
            team=other_team,
            path="Other/Canvas",
            depth=2,
            type="dashboard",
            surface="desktop",
            meta={"kind": "freeform"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/desktop_file_system/{other_canvas.id}/canvas/source/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("posthog.api.file_system.canvas_application.build_canvas.delay")
    @patch("posthog.models.file_system.canvas.object_storage.read_bytes")
    @patch("posthog.models.file_system.canvas.object_storage.write")
    def test_a_task_run_cannot_publish_two_versions_to_one_canvas(self, write: Any, read: Any, delay: Any) -> None:
        write.side_effect = self.object_write
        read.side_effect = self.object_read
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(self.source_url(), self.publish_payload())
        payload = self.publish_payload("again", expected=first.json()["version"]["id"])

        response = self.client.post(self.source_url(), payload)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertEqual(CanvasSourceVersion.objects.for_team(self.team.id).count(), 1)

    @patch("posthog.tasks.canvas_builds.tasks_facade.post_canvas_created_thread_update")
    @patch("posthog.tasks.canvas_builds.tasks_facade.post_canvas_build_thread_update")
    @patch("posthog.tasks.canvas_builds.object_storage.write")
    @patch("posthog.api.file_system.canvas_application.build_canvas.delay")
    @patch("posthog.models.file_system.canvas.object_storage.read_bytes")
    @patch("posthog.models.file_system.canvas.object_storage.write")
    def test_only_the_current_source_build_activates_and_failed_builds_keep_last_good(
        self,
        source_write: Any,
        source_read: Any,
        delay: Any,
        artifact_write: Any,
        build_update: Any,
        created_update: Any,
    ) -> None:
        source_write.side_effect = self.object_write
        source_read.side_effect = self.object_read
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(self.source_url(), self.publish_payload("first"))
        second_run = tasks_api.create_run(self.task_id)
        second_payload = self.publish_payload("second", expected=first.json()["version"]["id"])
        second_payload["taskRunId"] = str(second_run.id)
        with self.captureOnCommitCallbacks(execute=True):
            second = self.client.post(self.source_url(), second_payload)

        first_build = (
            CanvasBuild.objects.for_team(self.team.id)
            .select_related("source_version", "canvas")
            .get(id=first.json()["build"]["id"])
        )
        second_build = (
            CanvasBuild.objects.for_team(self.team.id)
            .select_related("source_version", "canvas")
            .get(id=second.json()["build"]["id"])
        )
        artifacts, manifest = ready_artifact()
        _complete_build(first_build, artifacts, manifest)
        application = CanvasApplication.objects.for_team(self.team.id).get(canvas_id=self.canvas_id)
        self.assertIsNone(application.active_build_id)

        _complete_build(second_build, artifacts, manifest)
        application.refresh_from_db()
        self.assertEqual(application.active_build_id, second_build.id)
        detail = self.client.get(f"/api/projects/{self.team.id}/desktop_file_system/{self.canvas_id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.json())
        self.assertIn("/canvas-artifacts/", detail.json()["meta"]["activeBuildArtifactUrl"])
        self.assertEqual(detail.json()["meta"]["activeBuildCapabilities"], manifest["capabilities"])

        third_run = tasks_api.create_run(self.task_id)
        third_payload = self.publish_payload("third", expected=second.json()["version"]["id"])
        third_payload["taskRunId"] = str(third_run.id)
        with self.captureOnCommitCallbacks(execute=True):
            third = self.client.post(self.source_url(), third_payload)
        third_build = (
            CanvasBuild.objects.for_team(self.team.id)
            .select_related("source_version", "canvas")
            .get(id=third.json()["build"]["id"])
        )
        _fail_build(third_build, [{"severity": "error", "code": "compile_error", "message": "Broken"}])
        application.refresh_from_db()
        self.assertEqual(application.active_build_id, second_build.id)

        artifact_write.assert_called()
        build_update.assert_called()
        created_update.assert_not_called()

    @patch("posthog.tasks.canvas_builds.object_storage.delete_objects")
    @patch("posthog.tasks.canvas_builds.object_storage.list_objects")
    @patch("posthog.api.file_system.canvas_application.build_canvas.delay")
    @patch("posthog.models.file_system.canvas.object_storage.read_bytes")
    @patch("posthog.models.file_system.canvas.object_storage.write")
    def test_retention_expires_only_unprotected_build_artifacts(
        self,
        source_write: Any,
        source_read: Any,
        delay: Any,
        list_objects: Any,
        delete_objects: Any,
    ) -> None:
        source_write.side_effect = self.object_write
        source_read.side_effect = self.object_read
        with self.captureOnCommitCallbacks(execute=True):
            published = self.client.post(self.source_url(), self.publish_payload())
        version = CanvasSourceVersion.objects.for_team(self.team.id).get(id=published.json()["version"]["id"])
        old = timezone.now() - timedelta(days=31)
        active = CanvasBuild.objects.for_team(self.team.id).get(id=published.json()["build"]["id"])
        active.artifact_object_prefix = f"canvas/artifacts/{self.team.id}/{active.id}"
        active.completed_at = old
        active.build_status = CanvasBuild.Status.READY
        active.save(update_fields=["artifact_object_prefix", "completed_at", "build_status"])
        expired = CanvasBuild.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            canvas_id=self.canvas_id,
            source_version=version,
            build_status=CanvasBuild.Status.READY,
            artifact_object_prefix=f"canvas/artifacts/{self.team.id}/expired",
            completed_at=old,
        )
        pinned = CanvasBuild.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            canvas_id=self.canvas_id,
            source_version=version,
            build_status=CanvasBuild.Status.READY,
            artifact_object_prefix=f"canvas/artifacts/{self.team.id}/pinned",
            completed_at=old,
            pinned=True,
        )
        application = CanvasApplication.objects.for_team(self.team.id).get(canvas_id=self.canvas_id)
        application.active_build = active
        application.save(update_fields=["active_build"])
        list_objects.side_effect = lambda prefix: (
            [f"{expired.artifact_object_prefix}/index.html"] if prefix == expired.artifact_object_prefix else []
        )

        collect_canvas_objects()

        active.refresh_from_db()
        expired.refresh_from_db()
        pinned.refresh_from_db()
        self.assertIsNotNone(active.artifact_object_prefix)
        self.assertIsNone(expired.artifact_object_prefix)
        self.assertIsNotNone(pinned.artifact_object_prefix)
        delete_objects.assert_called_once_with([f"canvas/artifacts/{self.team.id}/expired/index.html"])


def ready_artifact() -> tuple[dict[str, bytes], dict[str, Any]]:
    import hashlib

    content = b"<h1>Ready</h1>"
    return {"index.html": content}, {
        "schemaVersion": 1,
        "entryHtml": "index.html",
        "files": [
            {
                "path": "index.html",
                "contentType": "text/html; charset=utf-8",
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
        "canvasSdkVersion": "1.0.0",
        "dependencies": {},
        "capabilities": {
            "posthog": {"insights": [], "inlineQueries": False, "captureEvents": []},
            "network": {"origins": []},
        },
    }
