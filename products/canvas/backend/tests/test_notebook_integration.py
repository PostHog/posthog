from django.test import SimpleTestCase

from parameterized import parameterized

from products.canvas.backend.notebook_integration import validate_notebook_canvas_source


class TestNotebookCanvasSourceValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("computed_frame", 'ph["readFrame"]("private_df")', "notebook_frame_indirect_access"),
            ("aliased_frame", 'const read = ph.readFrame; read("private_df")', "notebook_frame_indirect_access"),
            (
                "destructured_frame",
                'const { readFrame } = ph; readFrame("private_df")',
                "notebook_frame_indirect_access",
            ),
            (
                "direct_state",
                'ph.state.get("__posthog_notebook_frame__:private_df:0:100")',
                "notebook_state_access_not_allowed",
            ),
            ("location_assignment", 'location.href = "https://example.com"', "notebook_navigation_not_allowed"),
            ("computed_location", 'window["location"] = "https://example.com"', "notebook_navigation_not_allowed"),
            ("open", 'open("https://example.com")', "notebook_navigation_not_allowed"),
        ]
    )
    def test_rejects_source_that_bypasses_the_notebook_boundary(
        self, _name: str, source: str, expected_code: str
    ) -> None:
        diagnostics = validate_notebook_canvas_source(source, ["public_df"])

        self.assertIn(expected_code, {diagnostic["code"] for diagnostic in diagnostics})

    def test_accepts_a_direct_allowed_frame_read(self) -> None:
        diagnostics = validate_notebook_canvas_source('void ph.readFrame("public_df")', ["public_df"])

        self.assertFalse([diagnostic for diagnostic in diagnostics if diagnostic["severity"] == "error"])
