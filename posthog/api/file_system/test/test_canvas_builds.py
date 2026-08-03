from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from posthog.api.file_system import canvas_build_service
from posthog.api.file_system.canvas_build_service import cleanup_canvas_builds, run_canvas_build
from posthog.api.file_system.canvas_source import CANVAS_COMPONENT_PATH, CANVAS_ENTRY_HTML
from posthog.models.file_system.canvas_build import CanvasBuild, CanvasSourceVersion
from posthog.models.file_system.file_system import FileSystem
from posthog.storage.object_storage import ObjectStorageError

CODE_V1 = 'import React from "react";\nexport default () => <div>v1</div>;\n'
CODE_V2 = 'import React from "react";\nexport default () => <div>v2</div>;\n'


class FakeObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def write(self, key: str, content: bytes | str, extras: dict | None = None, bucket: str | None = None) -> None:
        self.objects[key] = content if isinstance(content, bytes) else content.encode("utf-8")

    def read_bytes(self, key: str, bucket: str | None = None, **kwargs: Any) -> bytes | None:
        return self.objects.get(key)

    def delete_objects(self, keys: list[str], bucket: str | None = None) -> list[str]:
        self.deleted.extend(keys)
        for key in keys:
            self.objects.pop(key, None)
        return keys


class TestCanvasBuildLifecycle(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.storage = FakeObjectStorage()
        for attribute in ("write", "read_bytes", "delete_objects"):
            patcher = patch.object(canvas_build_service.object_storage, attribute, getattr(self.storage, attribute))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _base_url(self) -> str:
        return f"/api/projects/{self.team.id}/desktop_file_system/"

    def _create_canvas(self) -> UUID:
        channel = self.client.post(self._base_url(), {"path": "MyChannel", "type": "folder"}).json()
        response = self.client.post(f"{self._base_url()}canvases/", {"name": "MyCanvas", "channel_id": channel["id"]})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return UUID(response.json()["id"])

    def _project(self, code: str) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "files": {CANVAS_COMPONENT_PATH: code},
            "entryHtml": CANVAS_ENTRY_HTML,
            "dependencies": {"react": "19.0.0"},
            "canvasSdkVersion": "0.1.0",
        }

    def _publish(self, canvas_id: UUID, code: str, expected: str | None = "omit") -> Any:
        body: dict[str, Any] = {"project": self._project(code)}
        if expected != "omit":
            body["expected_current_version_id"] = expected
        return self.client.post(f"{self._base_url()}{canvas_id}/canvas/publish/", body, format="json")

    def test_publish_records_source_version_and_queued_build_atomically(self):
        canvas_id = self._create_canvas()

        with patch("posthog.tasks.canvas_build.process_canvas_build.delay") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                response = self._publish(canvas_id, CODE_V1)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        version = CanvasSourceVersion.objects.for_team(self.team.id).get(canvas_id=canvas_id)
        build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=canvas_id)
        self.assertEqual(build.status, CanvasBuild.STATUS_QUEUED)
        self.assertEqual(build.source_version_id, version.id)
        self.assertIsNone(version.parent_version_id)
        # The source object was uploaded under a content-addressed key before commit.
        self.assertIn(version.source_object_key, self.storage.objects)
        self.assertIn(version.source_hash, version.source_object_key)
        # The canvas head points at the new source version; the build worker
        # was queued on commit; no build is published yet.
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual(meta["currentSourceVersionId"], str(version.id))
        self.assertNotIn("publishedBuildId", meta)
        enqueue.assert_called_once_with(self.team.id, str(build.id))
        # The legacy history entry and the normalized row stay correlatable.
        self.assertEqual(version.legacy_version_id, meta["currentVersionId"])

    def test_ready_build_advances_published_pointer(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)
        build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=canvas_id)

        run_canvas_build(self.team.id, str(build.id))

        build.refresh_from_db()
        self.assertEqual(build.status, CanvasBuild.STATUS_READY)
        self.assertIsNotNone(build.integrity)
        manifest = cast(dict, build.manifest)
        self.assertEqual(manifest["legacyCode"], CODE_V1)
        self.assertEqual(manifest["entryHtml"], CANVAS_ENTRY_HTML)
        asset_paths = {asset["path"] for asset in manifest["assets"]}
        self.assertIn(CANVAS_ENTRY_HTML, asset_paths)
        self.assertTrue(any(path.endswith(".js") for path in asset_paths), asset_paths)
        # Artifact files are immutable objects under the build's prefix.
        for asset in manifest["assets"]:
            self.assertIn(f"{build.artifact_object_prefix}/{asset['path']}", self.storage.objects)
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual(meta["publishedBuildId"], str(build.id))

    def test_new_publish_supersedes_an_older_queued_build(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)
        first_build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=canvas_id)
        self._publish(canvas_id, CODE_V2)
        second_build = CanvasBuild.objects.for_team(self.team.id).exclude(id=first_build.id).get(canvas_id=canvas_id)
        first_build.refresh_from_db()
        self.assertEqual(first_build.status, CanvasBuild.STATUS_FAILED)
        self.assertEqual(first_build.diagnostics[0]["code"], "superseded")

        run_canvas_build(self.team.id, str(second_build.id))
        run_canvas_build(self.team.id, str(first_build.id))

        first_build.refresh_from_db()
        self.assertEqual(first_build.status, CanvasBuild.STATUS_FAILED)
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual(meta["publishedBuildId"], str(second_build.id))

    def test_publish_rejects_when_team_build_capacity_is_exhausted(self):
        canvas_id = self._create_canvas()
        with patch("posthog.api.file_system.file_system.MAX_ACTIVE_CANVAS_BUILDS_PER_TEAM", 0):
            response = self._publish(canvas_id, CODE_V1)

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertFalse(CanvasBuild.objects.for_team(self.team.id).filter(canvas_id=canvas_id).exists())

    def test_failed_build_keeps_last_known_good_published(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)
        good_build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=canvas_id)
        run_canvas_build(self.team.id, str(good_build.id))

        self._publish(canvas_id, CODE_V2)
        bad_build = CanvasBuild.objects.for_team(self.team.id).exclude(id=good_build.id).get(canvas_id=canvas_id)
        # The recorded source object goes missing before the worker runs.
        self.storage.objects.pop(bad_build.source_version.source_object_key)

        run_canvas_build(self.team.id, str(bad_build.id))

        bad_build.refresh_from_db()
        self.assertEqual(bad_build.status, CanvasBuild.STATUS_FAILED)
        self.assertEqual(bad_build.diagnostics[0]["code"], "source_unreadable")
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual(meta["publishedBuildId"], str(good_build.id))

    def test_active_build_lease_prevents_duplicate_execution(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)
        build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=canvas_id)
        build.status = CanvasBuild.STATUS_BUILDING
        build.lease_expires_at = timezone.now() + timedelta(minutes=1)
        build.save(update_fields=["status", "lease_expires_at"])

        with patch.object(canvas_build_service, "run_cloud_builder") as runner:
            run_canvas_build(self.team.id, str(build.id))

        runner.assert_not_called()

    def test_expired_build_lease_is_reclaimed(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)
        build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=canvas_id)
        build.status = CanvasBuild.STATUS_BUILDING
        build.attempt_count = 1
        build.lease_expires_at = timezone.now() - timedelta(seconds=1)
        build.save(update_fields=["status", "attempt_count", "lease_expires_at"])

        run_canvas_build(self.team.id, str(build.id))

        build.refresh_from_db()
        self.assertEqual(build.status, CanvasBuild.STATUS_READY)
        self.assertEqual(build.attempt_count, 2)
        self.assertIsNone(build.lease_expires_at)

    def test_conflicting_publish_creates_no_lifecycle_rows(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)

        response = self._publish(canvas_id, CODE_V2, expected="not-the-head")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(CanvasSourceVersion.objects.for_team(self.team.id).filter(canvas_id=canvas_id).count(), 1)
        self.assertEqual(CanvasBuild.objects.for_team(self.team.id).filter(canvas_id=canvas_id).count(), 1)

    def test_second_publish_links_parent_version(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)
        first = CanvasSourceVersion.objects.for_team(self.team.id).get(canvas_id=canvas_id)

        self._publish(canvas_id, CODE_V2)

        second = CanvasSourceVersion.objects.for_team(self.team.id).exclude(id=first.id).get(canvas_id=canvas_id)
        self.assertEqual(second.parent_version_id, first.id)

    def test_storage_outage_degrades_to_legacy_only_publish(self):
        canvas_id = self._create_canvas()

        with patch.object(canvas_build_service.object_storage, "write", side_effect=ObjectStorageError("down")):
            response = self._publish(canvas_id, CODE_V1)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        meta = cast(dict, FileSystem.objects.get(id=canvas_id).meta)
        self.assertEqual(meta["code"], CODE_V1)
        self.assertFalse(CanvasSourceVersion.objects.for_team(self.team.id).filter(canvas_id=canvas_id).exists())

    def test_builds_endpoint_reports_lifecycle(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)
        build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=canvas_id)
        run_canvas_build(self.team.id, str(build.id))

        response = self.client.get(f"{self._base_url()}{canvas_id}/canvas/builds/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        self.assertEqual(body["published_build_id"], str(build.id))
        self.assertEqual(body["builds"][0]["build_status"], "ready")
        self.assertEqual(body["builds"][0]["manifest"]["legacyCode"], CODE_V1)

    def test_failed_build_can_be_retried_and_ready_build_can_be_pinned(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)
        build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=canvas_id)
        build.status = CanvasBuild.STATUS_FAILED
        build.finished_at = timezone.now()
        build.save(update_fields=["status", "finished_at"])

        with patch("posthog.tasks.canvas_build.process_canvas_build.delay") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    f"{self._base_url()}{canvas_id}/canvas/builds/action/",
                    {"action": "retry", "build_id": str(build.id)},
                    format="json",
                )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        retried = CanvasBuild.objects.for_team(self.team.id).get(id=response.json()["id"])
        enqueue.assert_called_once_with(self.team.id, str(retried.id))
        run_canvas_build(self.team.id, str(retried.id))
        pin = self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/builds/action/",
            {"action": "pin", "build_id": str(retried.id)},
            format="json",
        )
        self.assertEqual(pin.status_code, status.HTTP_200_OK, pin.json())
        retried.refresh_from_db()
        self.assertTrue(retried.pinned)

    def test_queued_build_can_be_cancelled(self):
        canvas_id = self._create_canvas()
        self._publish(canvas_id, CODE_V1)
        build = CanvasBuild.objects.for_team(self.team.id).get(canvas_id=canvas_id)

        response = self.client.post(
            f"{self._base_url()}{canvas_id}/canvas/builds/action/",
            {"action": "cancel", "build_id": str(build.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        build.refresh_from_db()
        self.assertEqual(build.status, CanvasBuild.STATUS_FAILED)
        self.assertEqual(build.diagnostics[0]["code"], "cancelled")

    def test_retention_prunes_stale_artifacts_but_keeps_active_rollback_and_pinned(self):
        canvas_id = self._create_canvas()
        build_ids = []
        for code in ("v1", "v2", "v3", "v4"):
            self._publish(canvas_id, code)
            build = (
                CanvasBuild.objects.for_team(self.team.id)
                .filter(canvas_id=canvas_id, status=CanvasBuild.STATUS_QUEUED)
                .get()
            )
            run_canvas_build(self.team.id, str(build.id))
            build_ids.append(str(build.id))
        # Age every build past the successful-build retention window; pin v1.
        CanvasBuild.objects.for_team(self.team.id).update(finished_at=timezone.now() - timedelta(days=45))
        CanvasBuild.objects.for_team(self.team.id).filter(id=build_ids[0]).update(pinned=True)

        pruned = cleanup_canvas_builds()

        # v4 is active, v3 is the rollback, v1 is pinned — only v2 loses artifacts.
        self.assertEqual(pruned, 1)
        remaining = {
            str(build.id): build.artifact_object_prefix
            for build in CanvasBuild.objects.for_team(self.team.id).filter(canvas_id=canvas_id)
        }
        self.assertIsNone(remaining[build_ids[1]])
        self.assertIsNotNone(remaining[build_ids[0]])
        self.assertIsNotNone(remaining[build_ids[2]])
        self.assertIsNotNone(remaining[build_ids[3]])
        self.assertTrue(any("canvas_artifact/" in key for key in self.storage.deleted))
