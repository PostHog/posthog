import hashlib
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.api.file_system.canvas_build_service import run_cloud_builder, validate_builder_output


class TestCanvasCloudBuilder(SimpleTestCase):
    def _project(self, source: str) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "files": {
                "index.html": '<div id="root"></div><script type="module" src="/src/main.ts"></script>',
                "src/main.ts": source,
            },
            "entryHtml": "index.html",
            "dependencies": {},
            "canvasSdkVersion": "0.1.0",
        }

    def test_builds_vanilla_typescript_with_the_shared_contract(self) -> None:
        result = run_cloud_builder(self._project('document.querySelector("#root")!.textContent = "Hello"'))

        files, manifest, diagnostics = validate_builder_output(result)
        self.assertEqual(diagnostics, [])
        self.assertEqual(manifest["entryHtml"], "index.html")
        self.assertTrue(any(file["path"].endswith(".js") for file in files))

    def test_rejects_undeclared_package_imports(self) -> None:
        result = run_cloud_builder(self._project('import React from "react"; void React'))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["diagnostics"][0]["code"], "import_not_declared")

    def test_rejects_artifact_content_that_does_not_match_manifest(self) -> None:
        result = {
            "contractVersion": 1,
            "status": "ready",
            "diagnostics": [],
            "files": [{"path": "index.html", "content": "tampered", "contentHash": hashlib.sha256(b"safe").hexdigest(), "sizeBytes": 4}],
            "manifest": {"entryHtml": "index.html", "assets": []},
        }

        with self.assertRaisesMessage(ValueError, "integrity"):
            validate_builder_output(result)

    @patch("posthog.api.file_system.canvas_build_service.subprocess.run")
    def test_builder_has_bounded_process_resources(self, run: Any) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = '{"contractVersion":1,"status":"failed","diagnostics":[]}'

        run_cloud_builder({"files": {}})

        args, kwargs = run.call_args
        self.assertEqual(args[0][:2], ["node", "--max-old-space-size=256"])
        self.assertEqual(kwargs["timeout"], 45)
        self.assertEqual(kwargs["env"], {"PATH": "/usr/local/bin:/usr/bin:/bin", "NODE_ENV": "production"})
