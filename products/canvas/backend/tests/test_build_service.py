import hashlib
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.canvas.backend import build_service
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.canvas.backend.source import synthetic_source_project
from products.canvas.backend.tests.test_canvas_api import InMemoryStorage
from products.tasks.backend.models import Channel, Task, TaskThreadMessage


def _builder_result(files: dict[str, str], capabilities: dict | None = None) -> dict:
    manifest_assets = []
    emitted = []
    for path, content in files.items():
        digest = hashlib.sha256(content.encode()).hexdigest()
        manifest_assets.append({"path": path, "contentHash": digest, "sizeBytes": len(content.encode())})
        emitted.append({"path": path, "content": content, "contentHash": digest, "sizeBytes": len(content.encode())})
    return {
        "contractVersion": 1,
        "status": "ready",
        "diagnostics": [],
        "files": emitted,
        "manifest": {
            "entryHtml": "index.html",
            "assets": manifest_assets,
            "dependencies": {},
            "canvasSdkVersion": "0.1.0",
            "capabilities": capabilities
            or {"posthog": {"insights": [], "inlineQueries": False, "captureEvents": []}, "network": {"origins": []}},
        },
    }


class BuildServiceBaseTest(APIBaseTest):
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
            self.channel = Channel.objects.create(team=self.team, name="general")
            self.canvas = Canvas.objects.create(team=self.team, channel=self.channel, name="C")

    def _publish(self) -> CanvasBuild:
        _, _, build, _ = build_service.publish_source_project(
            self.canvas,
            project=synthetic_source_project("export default function C() { return null }"),
            prompt=None,
            name=None,
            has_expected_version=False,
            expected_version_id=None,
            task_id=None,
            created_by=None,
        )
        self.canvas.refresh_from_db()
        return build


class TestRunCanvasBuild(BuildServiceBaseTest):
    def test_ready_build_advances_published_pointer(self):
        build = self._publish()
        with patch.object(
            build_service, "run_cloud_builder", return_value=_builder_result({"index.html": "<html></html>"})
        ):
            build_service.run_canvas_build(self.team.id, str(build.id))

        build.refresh_from_db()
        self.canvas.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_READY
        assert build.artifact_object_prefix
        assert self.canvas.published_build_id == build.id
        entry_key = f"{build.artifact_object_prefix}/index.html"
        assert self.storage.objects[entry_key] == b"<html></html>"

    def test_draft_build_ready_does_not_advance_pointer(self):
        published = self._publish()
        with patch.object(
            build_service, "run_cloud_builder", return_value=_builder_result({"index.html": "<html></html>"})
        ):
            build_service.run_canvas_build(self.team.id, str(published.id))
        self.canvas.refresh_from_db()

        _version, draft_build, _widening = build_service.create_draft_version(
            self.canvas,
            project=synthetic_source_project("export default function C() { return 2 }"),
            prompt=None,
            task_id=None,
            created_by=None,
        )
        with patch.object(
            build_service, "run_cloud_builder", return_value=_builder_result({"index.html": "<html>2</html>"})
        ):
            build_service.run_canvas_build(self.team.id, str(draft_build.id))

        draft_build.refresh_from_db()
        self.canvas.refresh_from_db()
        assert draft_build.status == CanvasBuild.STATUS_READY
        assert draft_build.artifact_object_prefix
        assert self.canvas.published_build_id == published.id

    def test_stale_head_does_not_advance_pointer(self):
        build = self._publish()
        second = self._publish()  # supersedes the first build, moves the head
        with patch.object(
            build_service, "run_cloud_builder", return_value=_builder_result({"index.html": "<html></html>"})
        ):
            build_service.run_canvas_build(self.team.id, str(second.id))
            # The first build was superseded (failed) — running it again is a no-op.
            build_service.run_canvas_build(self.team.id, str(build.id))

        self.canvas.refresh_from_db()
        assert self.canvas.published_build_id == second.id

    def test_builder_failure_records_diagnostics_and_keeps_pointer(self):
        build = self._publish()
        with patch.object(
            build_service, "run_cloud_builder", return_value=_builder_result({"index.html": "<html></html>"})
        ):
            build_service.run_canvas_build(self.team.id, str(build.id))
        self.canvas.refresh_from_db()

        failing = self._publish()
        with patch.object(
            build_service,
            "run_cloud_builder",
            return_value={
                "contractVersion": 1,
                "status": "failed",
                "diagnostics": [{"severity": "error", "code": "bundle_error", "message": "boom"}],
            },
        ):
            build_service.run_canvas_build(self.team.id, str(failing.id))

        failing.refresh_from_db()
        self.canvas.refresh_from_db()
        assert failing.status == CanvasBuild.STATUS_FAILED
        assert failing.diagnostics[0]["code"] == "bundle_error"
        assert self.canvas.published_build_id == build.id

    def test_failed_build_files_report_in_authoring_task_thread(self):
        # A failed build must reach the authoring task's thread — dropping this
        # hook makes build failures silent again (telemetry only, nobody told).
        # A cancelled build is churn, not a defect, and must not be reported.
        task = Task.objects.create(
            team=self.team,
            channel=self.channel,
            created_by=self.user,
            title="Build canvas",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        Canvas.objects.unscoped().filter(id=self.canvas.id).update(generation_task_id=task.id)
        flag = patch("products.tasks.backend.facade.api._agent_thread_updates_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

        failing = self._publish()
        with patch.object(
            build_service,
            "run_cloud_builder",
            return_value={
                "contractVersion": 1,
                "status": "failed",
                "diagnostics": [{"severity": "error", "code": "bundle_error", "message": "boom"}],
            },
        ):
            build_service.run_canvas_build(self.team.id, str(failing.id))

        reports = TaskThreadMessage.objects.for_team(self.team.id).filter(
            task_id=task.id, event="canvas_error_reported"
        )
        assert reports.count() == 1
        payload = reports.get().payload
        assert payload["origin"] == "build"
        assert payload["build_id"] == str(failing.id)
        assert payload["error_codes"] == ["bundle_error"]

        cancelled = self._publish()
        build_service.act_on_build(self.canvas, cancelled.id, "cancel")
        assert reports.count() == 1

    def test_builder_crash_fails_with_generic_unavailable(self):
        build = self._publish()
        with patch.object(build_service, "run_cloud_builder", side_effect=RuntimeError("node exploded: secret path")):
            build_service.run_canvas_build(self.team.id, str(build.id))
        build.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_FAILED
        assert build.diagnostics[0]["code"] == "build_unavailable"
        # Outside DEBUG the diagnostic stays generic: builder stderr is internal.
        assert build.diagnostics[0]["message"] == "The canvas build service is unavailable."

    @override_settings(DEBUG=True)
    def test_builder_crash_names_the_cause_in_debug(self):
        build = self._publish()
        with patch.object(
            build_service,
            "run_cloud_builder",
            side_effect=RuntimeError("canvas builder dependencies are not installed — run `npm ci`"),
        ):
            build_service.run_canvas_build(self.team.id, str(build.id))
        build.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_FAILED
        assert build.diagnostics[0]["code"] == "build_unavailable"
        assert "npm ci" in build.diagnostics[0]["message"]

    def test_finished_build_is_a_noop(self):
        build = self._publish()
        CanvasBuild.objects.unscoped().filter(id=build.id).update(status=CanvasBuild.STATUS_READY)
        build_service.run_canvas_build(self.team.id, str(build.id))
        build.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_READY

    def test_finalize_does_not_clobber_a_concurrent_cancel(self):
        # The finalize transaction must re-claim the build row before marking it
        # READY: a cancel that lands during the long build/upload phase (after the
        # claim lock was released) turns the build FAILED/terminal, and the stale
        # in-memory object must not flip it back to READY.
        build = self._publish()

        original_finalize = build_service._finalize_ready

        def cancel_mid_finalize(*args, **kwargs):
            # Simulate the worker losing the row to a cancel between the claim
            # (lock released) and the finalize write.
            CanvasBuild.objects.unscoped().filter(id=build.id).update(
                status=CanvasBuild.STATUS_FAILED,
                diagnostics=[{"severity": "warning", "code": "cancelled", "message": "cancelled"}],
                finished_at=timezone.now(),
                lease_expires_at=None,
            )
            return original_finalize(*args, **kwargs)

        with (
            patch.object(
                build_service, "run_cloud_builder", return_value=_builder_result({"index.html": "<html></html>"})
            ),
            patch.object(build_service, "_finalize_ready", side_effect=cancel_mid_finalize),
        ):
            build_service.run_canvas_build(self.team.id, str(build.id))

        build.refresh_from_db()
        self.canvas.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_FAILED
        assert self.canvas.published_build_id is None

    def test_losing_finalize_race_to_ready_winner_keeps_shared_artifacts(self) -> None:
        # Two attempts of the SAME build share the deterministic artifact prefix. When a
        # redelivered attempt finalizes READY while a stalled attempt is still uploading,
        # the loser must not delete the keys — the winner's manifest references them.
        build = self._publish()
        prefix = build_service.artifact_object_prefix(self.team.id, build.canvas_id, build.id)

        def winner_finalizes_mid_build(project: dict) -> dict:
            CanvasBuild.objects.unscoped().filter(id=build.id).update(
                status=CanvasBuild.STATUS_READY,
                artifact_object_prefix=prefix,
                finished_at=timezone.now(),
                lease_expires_at=None,
            )
            return _builder_result({"index.html": "<html></html>"})

        with patch.object(build_service, "run_cloud_builder", side_effect=winner_finalizes_mid_build):
            build_service.run_canvas_build(self.team.id, str(build.id))

        assert self.storage.objects[f"{prefix}/index.html"] == b"<html></html>"
        build.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_READY

    @parameterized.expand(
        [
            ("ready", _builder_result({"index.html": "<html></html>"}), []),
            (
                "failed",
                {
                    "contractVersion": 1,
                    "status": "failed",
                    "diagnostics": [{"severity": "error", "code": "bundle_error", "message": "boom"}],
                },
                ["bundle_error"],
            ),
        ]
    )
    def test_terminal_build_captures_its_outcome(self, outcome: str, builder_result: dict, error_codes: list[str]):
        # The capture is wrapped in a catch-all so telemetry never fails a build, which
        # would let a broken payload lose the event silently.
        build = self._publish()
        with patch.object(build_service, "ph_background_capture") as capture:
            with self.captureOnCommitCallbacks(execute=True):
                with patch.object(build_service, "run_cloud_builder", return_value=builder_result):
                    build_service.run_canvas_build(self.team.id, str(build.id))

        properties = capture.return_value.call_args.kwargs["properties"]
        assert capture.return_value.call_args.kwargs["event"] == "canvas build completed"
        assert properties["outcome"] == outcome
        assert properties["error_codes"] == error_codes
        assert properties["build_id"] == str(build.id)


class TestBuildDispatch(BuildServiceBaseTest):
    def test_flagged_in_team_dispatches_to_temporal_instead_of_celery(self) -> None:
        with (
            patch.object(build_service.posthoganalytics, "feature_enabled", return_value=True),
            patch("products.canvas.backend.temporal.client.execute_canvas_build_workflow") as start_workflow,
            self.captureOnCommitCallbacks(execute=True),
        ):
            build = self._publish()
        start_workflow.assert_called_once_with(self.team.id, str(build.id))
        self.enqueue.assert_not_called()

    @parameterized.expand(
        [
            ("flag_check_fails", RuntimeError("flag service down"), None),
            ("workflow_start_fails", True, RuntimeError("temporal down")),
        ]
    )
    def test_temporal_failure_falls_back_to_celery(
        self, _name: str, flag_result: bool | Exception, workflow_error: Exception | None
    ) -> None:
        with (
            patch.object(build_service.posthoganalytics, "feature_enabled", side_effect=[flag_result]),
            patch(
                "products.canvas.backend.temporal.client.execute_canvas_build_workflow",
                side_effect=workflow_error,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            build = self._publish()
        self.enqueue.assert_called_once_with(self.team.id, str(build.id))


class TestSweeper(BuildServiceBaseTest):
    def test_lease_expired_building_is_requeued_then_failed(self):
        build = self._publish()
        CanvasBuild.objects.unscoped().filter(id=build.id).update(
            status=CanvasBuild.STATUS_BUILDING,
            lease_expires_at=timezone.now() - timedelta(minutes=1),
            attempt_count=1,
        )
        counts = build_service.sweep_canvas_builds()
        assert counts["requeued"] == 1
        build.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_QUEUED

        CanvasBuild.objects.unscoped().filter(id=build.id).update(
            status=CanvasBuild.STATUS_BUILDING,
            lease_expires_at=timezone.now() - timedelta(minutes=1),
            attempt_count=build_service.MAX_BUILD_ATTEMPTS,
        )
        counts = build_service.sweep_canvas_builds()
        assert counts["failed"] == 1
        build.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_FAILED
        assert build.diagnostics[0]["code"] == "build_lease_expired"

    def test_stale_queued_is_redelivered_then_failed(self):
        build = self._publish()
        CanvasBuild.objects.unscoped().filter(id=build.id).update(
            created_at=timezone.now() - build_service.STALE_QUEUED_REDELIVERY_AFTER - timedelta(minutes=1),
            enqueued_at=timezone.now() - build_service.STALE_QUEUED_REDELIVERY_AFTER - timedelta(minutes=1),
        )
        self.enqueue.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            counts = build_service.sweep_canvas_builds()
        assert counts["redelivered"] == 1
        self.enqueue.assert_called_once_with(self.team.id, str(build.id))

        CanvasBuild.objects.unscoped().filter(id=build.id).update(
            created_at=timezone.now() - build_service.STALE_QUEUED_FAILURE_AFTER - timedelta(minutes=1),
            enqueued_at=timezone.now() - build_service.STALE_QUEUED_FAILURE_AFTER - timedelta(minutes=1),
        )
        counts = build_service.sweep_canvas_builds()
        assert counts["failed"] == 1
        build.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_FAILED

    def test_freshly_retried_build_is_not_redelivered(self):
        # A retry requeues a FAILED (hence old) build but leaves created_at alone.
        # The sweeper must key staleness off when the row was last enqueued, not
        # created, or it re-delivers a build a worker was already told about.
        build = self._publish()
        CanvasBuild.objects.unscoped().filter(id=build.id).update(
            status=CanvasBuild.STATUS_FAILED,
            created_at=timezone.now() - timedelta(hours=1),
            finished_at=timezone.now() - timedelta(minutes=30),
        )
        build_service.act_on_build(self.canvas, build.id, "retry")
        build.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_QUEUED

        self.enqueue.reset_mock()
        counts = build_service.sweep_canvas_builds()
        assert counts["redelivered"] == 0
        self.enqueue.assert_not_called()

    def test_live_builds_are_untouched(self):
        build = self._publish()
        CanvasBuild.objects.unscoped().filter(id=build.id).update(
            status=CanvasBuild.STATUS_BUILDING, lease_expires_at=timezone.now() + timedelta(minutes=4)
        )
        counts = build_service.sweep_canvas_builds()
        assert counts == {"requeued": 0, "failed": 0, "redelivered": 0}


class TestCleanup(BuildServiceBaseTest):
    def test_cleanup_prunes_aged_artifacts_but_keeps_published_and_pinned(self):
        published = self._publish()
        with patch.object(
            build_service, "run_cloud_builder", return_value=_builder_result({"index.html": "<html></html>"})
        ):
            build_service.run_canvas_build(self.team.id, str(published.id))
        self.canvas.refresh_from_db()

        old = timezone.now() - build_service.SUCCESSFUL_BUILD_RETENTION - timedelta(days=1)
        # Three more successful builds; the head (published pointer) ends on the
        # last one. Age everything, pin one — the prunable remainder is the
        # first build and the unpinned non-rollback middle ones.
        aged = [published]
        for _ in range(3):
            build = self._publish()
            with patch.object(
                build_service, "run_cloud_builder", return_value=_builder_result({"index.html": "<html></html>"})
            ):
                build_service.run_canvas_build(self.team.id, str(build.id))
            aged.append(build)
        CanvasBuild.objects.unscoped().filter(id__in=[b.id for b in aged]).update(finished_at=old)
        CanvasBuild.objects.unscoped().filter(id=aged[1].id).update(pinned=True)
        self.canvas.refresh_from_db()
        assert self.canvas.published_build_id == aged[-1].id

        pruned = build_service.cleanup_canvas_builds()

        kept = {
            str(b.id)
            for b in CanvasBuild.objects.unscoped().filter(
                canvas_id=self.canvas.id, artifact_object_prefix__isnull=False
            )
        }
        assert str(aged[1].id) in kept  # pinned
        assert str(self.canvas.published_build_id) in kept  # live pointer
        assert str(aged[2].id) in kept  # newest other ready build (instant rollback)
        assert str(published.id) not in kept  # aged past retention, unprotected
        assert pruned == 1


class TestLegacySourcePreservation(BuildServiceBaseTest):
    def test_first_publish_materializes_legacy_code_as_parent_version(self):
        legacy = "export default function Legacy() { return null }"
        Canvas.objects.unscoped().filter(id=self.canvas.id).update(legacy_code=legacy)
        self.canvas.refresh_from_db()

        canvas, version, _build, first_publish = build_service.publish_source_project(
            self.canvas,
            project=synthetic_source_project("export default function Rewrite() { return null }"),
            prompt="rewrite",
            name=None,
            has_expected_version=True,
            expected_version_id=None,
            task_id=None,
            created_by=None,
        )

        head = CanvasSourceVersion.objects.unscoped().get(pk=version.id)
        assert head.parent_version_id is not None
        legacy_version = CanvasSourceVersion.objects.unscoped().get(pk=head.parent_version_id)
        assert build_service.read_source_project(legacy_version) == synthetic_source_project(legacy)
        assert canvas.current_source_version_id == head.id
        assert canvas.legacy_code is None
        assert not first_publish

    def test_publish_on_fresh_canvas_creates_single_root_version(self):
        self._publish()

        versions = CanvasSourceVersion.objects.unscoped().filter(canvas_id=self.canvas.id)
        assert versions.count() == 1
        assert versions.get().parent_version_id is None
