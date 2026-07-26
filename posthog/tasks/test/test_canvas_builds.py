import hashlib
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.file_system.canvas_application import CanvasSourceProjectSerializer
from posthog.tasks.canvas_builds import MAX_ARTIFACT_FILES, _run_builder, _validated_artifacts, validate_canvas_project


def project(source: str, *, dependencies: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "files": {
            "index.html": '<div id="root"></div><script type="module" src="/src/main.ts"></script>',
            "src/main.ts": source,
        },
        "entryHtml": "index.html",
        "dependencies": dependencies or {},
        "canvasSdkVersion": "1.0.0",
        "capabilities": {
            "posthog": {"insights": [], "inlineQueries": False, "captureEvents": []},
            "network": {"origins": []},
        },
    }


class TestCanvasBuilder(SimpleTestCase):
    def test_builds_vanilla_typescript_with_csp_and_runtime(self) -> None:
        result = _run_builder(project('document.querySelector("#root")!.textContent = "Hello"'))

        self.assertTrue(result["ok"])
        self.assertIn("assets/main.js", result["artifactFiles"])
        self.assertIn("Content-Security-Policy", result["artifactFiles"]["index.html"])
        self.assertIn("assets/canvas-runtime.js", result["artifactFiles"])

    def test_validation_returns_manifest_without_executable_artifacts(self) -> None:
        result = validate_canvas_project(project('document.querySelector("#root")!.textContent = "Hello"'))

        self.assertTrue(result["ok"])
        self.assertEqual(result["manifest"]["entryHtml"], "index.html")
        self.assertNotIn("artifactFiles", result)

    @patch("posthog.tasks.canvas_builds._run_builder", side_effect=RuntimeError("private detail"))
    def test_validation_failure_does_not_leak_builder_internals(self, _run: Any) -> None:
        result = validate_canvas_project(project(""))

        self.assertFalse(result["ok"])
        self.assertEqual(result["diagnostics"][0]["code"], "validation_unavailable")
        self.assertNotIn("private detail", result["diagnostics"][0]["message"])

    @parameterized.expand(
        [
            ("node_builtin", 'import "node:fs"', "forbidden_import"),
            ("undeclared_package", 'import React from "react"; void React', "undeclared_dependency"),
            ("package_traversal", 'import "react/../../outside"', "forbidden_import"),
            ("dynamic_undeclared", 'void import("react")', "compile_error"),
        ]
    )
    def test_rejects_untrusted_imports(self, _name: str, source: str, expected_code: str) -> None:
        result = _run_builder(project(source))

        self.assertFalse(result["ok"])
        self.assertIn(expected_code, [diagnostic["code"] for diagnostic in result["diagnostics"]])

    def test_blocks_external_egress_even_when_declared_until_capability_approval_exists(self) -> None:
        payload = project('fetch("https://example.com/data")')
        payload["capabilities"]["network"]["origins"] = ["https://example.com"]

        result = _run_builder(payload)

        self.assertFalse(result["ok"])
        self.assertIn("network_capability_unavailable", [item["code"] for item in result["diagnostics"]])

    def test_builder_independently_rejects_an_unsupported_sdk(self) -> None:
        payload = project("")
        payload["canvasSdkVersion"] = "2.0.0"

        result = _run_builder(payload)

        self.assertFalse(result["ok"])
        self.assertIn("unsupported_sdk", [item["code"] for item in result["diagnostics"]])

    def test_rejects_artifact_content_that_does_not_match_manifest(self) -> None:
        content = b"safe"
        result = {
            "artifactFiles": {"index.html": "tampered"},
            "manifest": {
                "entryHtml": "index.html",
                "files": [
                    {
                        "path": "index.html",
                        "contentType": "text/html",
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            },
        }

        with self.assertRaisesMessage(ValueError, "integrity"):
            _validated_artifacts(result)

    @parameterized.expand(
        [
            ("event_handler", '<button onclick="alert(1)">Go</button>', "inline_event_handler"),
            ("javascript_url", '<a href="javascript:alert(1)">Go</a>', "javascript_url"),
        ]
    )
    def test_rejects_unsafe_html_execution_paths(self, _name: str, html: str, code: str) -> None:
        payload = project("")
        payload["files"] = {"index.html": html}

        result = _run_builder(payload)

        self.assertFalse(result["ok"])
        self.assertIn(code, [item["code"] for item in result["diagnostics"]])

    @parameterized.expand(
        [
            ("traversal", "../index.html"),
            ("absolute", "/index.html"),
            ("backslash", "src\\main.ts"),
            ("control_character", "src/ma\n in.ts"),
        ]
    )
    def test_source_serializer_rejects_unsafe_paths(self, _name: str, unsafe_path: str) -> None:
        payload = project("")
        payload["files"] = {unsafe_path: "", "index.html": ""}

        serializer = CanvasSourceProjectSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("files", serializer.errors)

    @parameterized.expand(
        [
            ("range", "react", "^19.2.6"),
            ("unknown", "left-pad", "1.3.0"),
            ("wrong_admitted_version", "react", "19.2.5"),
        ]
    )
    def test_source_serializer_rejects_unavailable_dependencies(
        self, _name: str, dependency: str, version: str
    ) -> None:
        payload = project("")
        payload["dependencies"] = {dependency: version}

        serializer = CanvasSourceProjectSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("dependencies", serializer.errors)

    def test_source_serializer_accepts_all_admitted_dependencies(self) -> None:
        payload = project("")
        payload["dependencies"] = {
            "@posthog/quill": "0.3.0-beta.24",
            "react": "19.2.6",
            "react-dom": "19.2.6",
            "three": "0.183.2",
        }

        serializer = CanvasSourceProjectSerializer(data=payload)

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_source_serializer_bounds_dependency_metadata(self) -> None:
        payload = project("")
        payload["dependencies"] = {f"package-{index}": "1.0.0" for index in range(65)}

        serializer = CanvasSourceProjectSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("dependencies", serializer.errors)

    def test_source_serializer_rejects_unsupported_sdk_versions(self) -> None:
        payload = project("")
        payload["canvasSdkVersion"] = "2.0.0"

        serializer = CanvasSourceProjectSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("canvasSdkVersion", serializer.errors)

    def test_rejects_duplicate_or_malformed_manifest_entries(self) -> None:
        digest = hashlib.sha256(b"safe").hexdigest()
        entry = {"path": "index.html", "contentType": "text/html", "bytes": 4, "sha256": digest}
        result = {
            "artifactFiles": {"index.html": "safe"},
            "manifest": {"entryHtml": "index.html", "files": [entry, entry]},
        }

        with self.assertRaisesMessage(ValueError, "invalid file"):
            _validated_artifacts(result)

    def test_rejects_excessive_manifest_before_decoding_artifacts(self) -> None:
        result = {
            "artifactFiles": {},
            "manifest": {"entryHtml": "index.html", "files": [{}] * (MAX_ARTIFACT_FILES + 1)},
        }

        with self.assertRaisesMessage(ValueError, "too many files"):
            _validated_artifacts(result)

    @patch("posthog.tasks.canvas_builds.subprocess.run")
    def test_builder_has_bounded_process_resources(self, run: Any) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "{}"

        _run_builder(project(""))

        args, kwargs = run.call_args
        self.assertEqual(args[0][:2], ["node", "--max-old-space-size=256"])
        self.assertEqual(kwargs["timeout"], 120)
        self.assertEqual(kwargs["env"], {"PATH": "/usr/local/bin:/usr/bin:/bin", "NODE_ENV": "production"})
