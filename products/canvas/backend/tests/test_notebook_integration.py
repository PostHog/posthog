from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.canvas.backend.models import Canvas
from products.canvas.backend.notebook_integration import (
    NotebookCanvasNotFoundError,
    create_notebook_canvas,
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

    def test_tool_calls_require_a_grant_and_literal_tool_name(self) -> None:
        missing_grant = validate_notebook_canvas_source('void ph.tools.call("annotations-create", {})', [])
        dynamic_name = validate_notebook_canvas_source("void ph.tools.call(toolName, {})", [], tool_access=True)
        allowed = validate_notebook_canvas_source('void ph.tools.call("annotations-create", {})', [], tool_access=True)

        assert any(item["code"] == "capability_missing_notebook_tools" for item in missing_grant)
        assert any(item["code"] == "notebook_tool_name_dynamic" for item in dynamic_name)
        assert not [item for item in allowed if item["severity"] == "error"]

    def test_dataframe_calls_require_a_grant(self) -> None:
        diagnostics = validate_notebook_canvas_source(
            'void ph.readFrame("public_df")', ["public_df"], notebook_data_access=False
        )

        assert any(item["code"] == "capability_missing_notebook_data" for item in diagnostics)


class TestNotebookCanvasCreation(APIBaseTest):
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
