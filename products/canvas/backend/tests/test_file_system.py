from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.unfiled_file_saver import save_unfiled_files
from posthog.models.scoping import team_scope

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
