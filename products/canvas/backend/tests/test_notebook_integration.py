import gzip
import json
import hashlib

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.storage.object_storage import ObjectStorageError

from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.canvas.backend.notebook_integration import (
    NotebookCanvasNotFoundError,
    cleanup_discarded_notebook_canvas_draft,
    create_notebook_canvas,
    discard_notebook_canvas_draft,
    get_notebook_canvas_source,
    requeue_discarded_notebook_canvas_drafts,
    validate_notebook_canvas_source,
)
from products.tasks.backend.models import Channel


class TestNotebookCanvasSourceValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("location_variable", "const location = row.city"),
            ("location_prop", "const marker = <Marker location={point} />"),
            ("open_comment", "// click to open (details)"),
            ("open_string", 'const label = "open (beta)"'),
        ]
    )
    def test_accepts_navigation_words_that_do_not_navigate(self, _name: str, source: str) -> None:
        diagnostics = validate_notebook_canvas_source(source, ["public_df"])

        self.assertFalse([diagnostic for diagnostic in diagnostics if diagnostic["severity"] == "error"])

    def test_accepts_a_direct_allowed_frame_read(self) -> None:
        diagnostics = validate_notebook_canvas_source('void ph.readFrame("public_df")', ["public_df"])

        self.assertFalse([diagnostic for diagnostic in diagnostics if diagnostic["severity"] == "error"])


class TestNotebookCanvasCreation(APIBaseTest):
    @parameterized.expand([("published", False), ("draft", True)])
    def test_reads_source_without_publishing_a_draft(self, _name: str, request_draft: bool) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team=self.team, name="Widget previews")
        canvas = Canvas.objects.for_team(self.team.id).create(
            team=self.team,
            channel=channel,
            name="Revenue widget",
            source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET,
        )
        source_objects: dict[str, bytes] = {}
        source_versions = []
        for is_draft in [False, True]:
            source = f"export default function Widget() {{ return <div>{'Draft' if is_draft else 'Published'}</div> }}"
            canonical = json.dumps({"files": {"src/canvas.tsx": source}}).encode()
            object_key = f"canvas_source/test-{'draft' if is_draft else 'published'}.json.gz"
            source_objects[object_key] = gzip.compress(canonical)
            source_versions.append(
                CanvasSourceVersion.objects.for_team(self.team.id).create(
                    team=self.team,
                    canvas=canvas,
                    draft=is_draft,
                    source_hash=hashlib.sha256(canonical).hexdigest(),
                    source_object_key=object_key,
                    source_size=len(canonical),
                )
            )
        canvas.current_source_version = source_versions[0]
        canvas.save(update_fields=["current_source_version"])

        if request_draft:
            with self.assertRaises(NotebookCanvasNotFoundError):
                get_notebook_canvas_source(team_id=self.team.id, canvas_id=canvas.id, version_id=source_versions[1].id)
        with patch("products.canvas.backend.build_service.object_storage.read_bytes", side_effect=source_objects.get):
            result = get_notebook_canvas_source(
                team_id=self.team.id,
                canvas_id=canvas.id,
                version_id=source_versions[1].id if request_draft else None,
                allow_draft=request_draft,
            )

        expected_label = "Draft" if request_draft else "Published"
        assert result == f"export default function Widget() {{ return <div>{expected_label}</div> }}"
        canvas.refresh_from_db()
        source_versions[1].refresh_from_db()
        assert canvas.current_source_version_id == source_versions[0].id
        assert source_versions[1].draft

    @parameterized.expand(
        [
            ("queued", CanvasBuild.STATUS_QUEUED, False, False),
            ("building", CanvasBuild.STATUS_BUILDING, False, False),
            ("shared_source", CanvasBuild.STATUS_READY, True, False),
            ("storage_retry", CanvasBuild.STATUS_READY, False, True),
        ]
    )
    def test_discard_cleans_up_only_the_abandoned_draft(
        self, _name: str, status: str, shared_source: bool, retry: bool
    ) -> None:
        channel = Channel.objects.for_team(self.team.id).create(team=self.team, name="Draft cleanup")
        canvas = Canvas.objects.for_team(self.team.id).create(
            team=self.team, channel=channel, source_policy=Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET
        )
        published = CanvasSourceVersion.objects.for_team(self.team.id).create(
            team=self.team,
            canvas=canvas,
            source_hash="a" * 64,
            source_object_key="canvas_source/published.json.gz",
            source_size=1,
        )
        canvas.current_source_version = published
        canvas.save(update_fields=["current_source_version"])
        draft = CanvasSourceVersion.objects.for_team(self.team.id).create(
            team=self.team,
            canvas=canvas,
            draft=True,
            source_hash="b" * 64,
            source_object_key=published.source_object_key if shared_source else "canvas_source/draft.json.gz",
            source_size=1,
        )
        build = CanvasBuild.objects.for_team(self.team.id).create(
            team=self.team,
            canvas=canvas,
            source_version=draft,
            status=status,
            artifact_object_prefix="canvas_artifact/draft" if status == CanvasBuild.STATUS_READY else None,
            manifest={"assets": [{"path": "index.html"}]},
        )
        with (
            patch("products.canvas.backend.tasks.cleanup_notebook_canvas_draft.delay") as enqueue,
            self.captureOnCommitCallbacks(execute=True),
        ):
            discard_notebook_canvas_draft(team_id=self.team.id, canvas_id=canvas.id, version_id=draft.id)
        enqueue.assert_called_once_with(self.team.id, str(canvas.id), str(draft.id))
        build.refresh_from_db()
        assert build.status == CanvasBuild.STATUS_FAILED
        with patch("posthog.storage.object_storage.delete_objects") as delete_objects:
            if retry:
                delete_objects.side_effect = ObjectStorageError("Storage temporarily unavailable")
                with self.assertRaises(ObjectStorageError):
                    cleanup_discarded_notebook_canvas_draft(
                        team_id=self.team.id, canvas_id=canvas.id, version_id=draft.id
                    )
                assert CanvasSourceVersion.objects.for_team(self.team.id).filter(id=draft.id).exists()
                with patch("products.canvas.backend.tasks.cleanup_notebook_canvas_draft.delay") as requeue:
                    requeue_discarded_notebook_canvas_drafts()
                requeue.assert_called_once_with(self.team.id, str(canvas.id), str(draft.id))
                delete_objects.side_effect = None
            cleanup_discarded_notebook_canvas_draft(team_id=self.team.id, canvas_id=canvas.id, version_id=draft.id)
            deleted = delete_objects.call_args.args[0]
            assert (draft.source_object_key in deleted) is not shared_source
            assert ("canvas_artifact/draft/index.html" in deleted) is (status == CanvasBuild.STATUS_READY)
        assert not CanvasSourceVersion.objects.for_team(self.team.id).filter(id=draft.id).exists()
        assert not CanvasBuild.objects.for_team(self.team.id).filter(id=build.id).exists()
        canvas.refresh_from_db()
        assert canvas.current_source_version_id == published.id
        with self.assertRaises(NotebookCanvasNotFoundError):
            discard_notebook_canvas_draft(team_id=self.team.id, canvas_id=canvas.id, version_id=published.id)

    def test_rejects_another_users_personal_channel(self) -> None:
        other_user = self._create_user("notebook-widget-channel-owner@example.com")
        with team_scope(self.team.id):
            channel = Channel.objects.create(
                team=self.team,
                name="Other member",
                channel_type=Channel.ChannelType.PERSONAL,
                created_by=other_user,
            )

        with self.assertRaises(NotebookCanvasNotFoundError):
            create_notebook_canvas(
                team_id=self.team.id,
                user_id=self.user.id,
                channel_id=channel.id,
                name="Widget",
                context="Context",
            )

        self.assertFalse(Canvas.objects.unscoped().filter(channel_id=channel.id).exists())

    def test_rejects_a_channel_from_another_team(self) -> None:
        other_team = self.create_team_with_organization(self.organization)
        with team_scope(other_team.id):
            channel = Channel.objects.create(team=other_team, name="Other team", created_by=self.user)

        with self.assertRaises(NotebookCanvasNotFoundError):
            create_notebook_canvas(
                team_id=self.team.id,
                user_id=self.user.id,
                channel_id=channel.id,
                name="Widget",
                context="Context",
            )

        self.assertFalse(Canvas.objects.unscoped().filter(channel_id=channel.id).exists())
