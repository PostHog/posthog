import os
import hashlib
import tempfile
import subprocess
from pathlib import Path
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.canvas.backend.build_service import node_executable, run_cloud_builder, validate_builder_output
from products.canvas.backend.presentation.serializers import CanvasSourceProjectSerializer
from products.canvas.backend.source import synthetic_source_project, validate_source_project


class TestCanvasCloudBuilder(SimpleTestCase):
    def test_legacy_canvas_build_mounts_react_and_injects_the_runtime_bridge(self) -> None:
        payload = synthetic_source_project(
            'import React from "react"; export default function Canvas() { return <div>Hello</div> }'
        )

        result = run_cloud_builder(payload)

        self.assertEqual(result["status"], "ready", result["diagnostics"])
        validate_builder_output(result)
        javascript = "\n".join(file["content"] for file in result["files"] if file["path"].endswith(".js"))
        html = next(file["content"] for file in result["files"] if file["path"] == "index.html")
        self.assertIn("createRoot", javascript)
        self.assertIn("canvas-runtime", html)

    def test_legacy_canvas_build_compiles_tailwind_and_quill_styles(self) -> None:
        payload = synthetic_source_project(
            'import { Button } from "@posthog/quill"; '
            'export default function Canvas() { return <div className="grid gap-4 p-6 md:grid-cols-2">'
            "<Button>Save</Button></div> }"
        )

        result = run_cloud_builder(payload)

        self.assertEqual(result["status"], "ready", result["diagnostics"])
        validate_builder_output(result)
        html = next(file["content"] for file in result["files"] if file["path"] == "index.html")
        stylesheet = next(
            file
            for file in result["files"]
            if file["path"].startswith("assets/canvas-platform-") and file["path"].endswith(".css")
        )
        self.assertIn(f"./{stylesheet['path']}", html)
        self.assertIn(".grid", stylesheet["content"])
        self.assertIn(".p-6", stylesheet["content"])
        self.assertIn(".md\\:grid-cols-2", stylesheet["content"])
        self.assertIn(".quill-button", stylesheet["content"])
        self.assertIn("--background", stylesheet["content"])

    def test_publication_validation_allows_relative_worker_and_asset_imports(self) -> None:
        payload = synthetic_source_project(
            'import workerUrl from "./sum.worker.ts?worker"; import image from "../assets/pixel.png"; void workerUrl; void image'
        )
        payload["files"]["src/sum.worker.ts"] = 'self.postMessage("ready")'
        payload["assets"] = {
            "assets/pixel.png": {"encoding": "base64", "contentType": "image/png", "content": "iVBORw0KGgo="}
        }

        diagnostics = validate_source_project(payload)

        self.assertNotIn("import_not_allowed", [item["code"] for item in diagnostics])

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
        self.assertFalse(manifest["capabilities"]["posthog"]["inlineQueries"])
        self.assertTrue(any(file["path"].endswith(".js") for file in files))

    def test_runtime_uses_the_document_bound_message_port(self) -> None:
        result = run_cloud_builder(self._project('document.body.textContent = "Hello"'))

        runtime = next(file["content"] for file in result["files"] if file["path"] == "assets/canvas-runtime.js")
        self.assertIn('event.data?.type!=="connect"', runtime)
        self.assertIn("event.ports[0]", runtime)
        self.assertIn("port?.postMessage", runtime)
        self.assertIn('event.data?.type==="set-comment-highlights"', runtime)
        self.assertIn('CSS.highlights.set("posthog-canvas-comment"', runtime)
        self.assertNotIn("ph-canvas-comment-outline", runtime)
        self.assertIn('type:"comment-activate"', runtime)
        self.assertIn("event.preventDefault();event.stopPropagation()", runtime)
        self.assertIn("if(!items.length||timer)return", runtime)
        self.assertNotIn("clearTimeout(timer);timer=setTimeout(()=>render(items),100)", runtime)
        self.assertIn('document.addEventListener("selectionchange"', runtime)
        self.assertNotIn('document.addEventListener("mouseup"', runtime)
        self.assertIn('event.data?.type==="clear-text-selection"', runtime)
        self.assertIn("getSelection()?.removeAllRanges()", runtime)
        self.assertIn("if(selection&&!selection.isCollapsed)return", runtime)
        self.assertNotIn("parent.postMessage({channel,...message}", runtime)

    def test_runtime_bounds_host_side_effects(self) -> None:
        result = run_cloud_builder(self._project('document.body.textContent = "Hello"'))

        runtime = next(file["content"] for file in result["files"] if file["path"] == "assets/canvas-runtime.js")
        self.assertIn('url.protocol!=="https:"', runtime)
        self.assertIn('url.hostname.endsWith(".posthog.com")', runtime)
        self.assertIn("serialized.length>16384", runtime)

    def test_runtime_applies_the_host_theme(self) -> None:
        result = run_cloud_builder(self._project('document.body.textContent = "Hello"'))

        runtime = next(file["content"] for file in result["files"] if file["path"] == "assets/canvas-runtime.js")
        harness = """
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const classes = new Set();
const toggles = [];
const style = {};
const listeners = { message: [] };
globalThis.window = globalThis;
globalThis.parent = {};
globalThis.location = { hash: "#theme=dark" };
globalThis.document = {
    readyState: "complete",
    body: {},
    head: { appendChild: () => {} },
    addEventListener: () => {},
    createElement: () => ({}),
    documentElement: {
        classList: {
            toggle: (name, force) => {
                toggles.push([name, force]);
                force ? classes.add(name) : classes.delete(name);
            },
        },
        style,
    },
};
globalThis.MutationObserver = class {
    observe() {}
};
globalThis.addEventListener = (type, handler) => (listeners[type] ??= []).push(handler);

new Function(readFileSync(new URL("./runtime.js", import.meta.url), "utf8"))();

assert.ok(classes.has("dark"), "the theme fragment did not add the dark class before connect");
assert.equal(style.colorScheme, "dark");

const bridge = new MessageChannel();
for (const handler of listeners.message) {
    handler({ source: globalThis.parent, data: { channel: "posthog-canvas", type: "connect" }, ports: [bridge.port2] });
}
bridge.port1.postMessage({ channel: "posthog-canvas", type: "set-theme", theme: "solarized" });
bridge.port1.postMessage({ channel: "posthog-canvas", type: "set-theme" });
bridge.port1.postMessage({ channel: "posthog-canvas", type: "set-theme", theme: "light" });
const deadline = Date.now() + 5000;
while (classes.has("dark") && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 10));
}
assert.ok(!classes.has("dark"), "the set-theme frame did not remove the dark class");
assert.equal(style.colorScheme, "light");
// Port delivery is ordered, so by the light flip the invalid frames were
// already processed — exactly two toggles proves they were ignored, not
// coerced to light.
assert.deepEqual(toggles, [["dark", true], ["dark", false]]);
bridge.port1.close();
"""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "runtime.js").write_text(runtime)
            (Path(directory) / "harness.mjs").write_text(harness)
            process = subprocess.run(
                [node_executable(), str(Path(directory) / "harness.mjs")],
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_freezes_declared_capabilities_into_manifest(self) -> None:
        project = self._project('document.body.textContent = "Hello"')
        project["capabilities"] = {
            "posthog": {"insights": ["abc"], "inlineQueries": False, "captureEvents": ["canvas viewed"]},
            "network": {"origins": []},
        }

        _, manifest, _ = validate_builder_output(run_cloud_builder(project))

        self.assertEqual(manifest["capabilities"], project["capabilities"])

    def test_rejects_unbounded_capabilities(self) -> None:
        project = self._project("")
        project["capabilities"] = {
            "posthog": {"insights": ["x"] * 101, "inlineQueries": False, "captureEvents": []},
            "network": {"origins": []},
        }

        serializer = CanvasSourceProjectSerializer(data=project)

        self.assertFalse(serializer.is_valid())
        self.assertIn("capabilities", serializer.errors)

    def test_rejects_undeclared_package_imports(self) -> None:
        result = run_cloud_builder(self._project('import React from "react"; void React'))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["diagnostics"][0]["code"], "import_not_declared")

    def test_rejects_prototype_chain_package_imports(self) -> None:
        for specifier in ("constructor", "toString", "__proto__"):
            result = run_cloud_builder(self._project(f'import value from "{specifier}"; void value'))

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["diagnostics"][0]["code"], "import_not_declared")

    def test_builds_binary_assets_and_module_workers(self) -> None:
        payload = self._project(
            'import image from "../assets/pixel.png"; import workerUrl from "./worker.ts?worker"; '
            'document.body.dataset.image = image; new Worker(workerUrl, { type: "module" })'
        )
        payload["files"]["src/worker.ts"] = 'self.postMessage("ready")'
        payload["assets"] = {
            "assets/pixel.png": {
                "encoding": "base64",
                "contentType": "image/png",
                "content": "iVBORw0KGgo=",
            },
            "assets/module.wasm": {
                "encoding": "base64",
                "contentType": "application/wasm",
                "content": "AGFzbQEAAAA=",
            },
        }

        result = run_cloud_builder(payload)

        self.assertEqual(result["status"], "ready", result["diagnostics"])
        javascript = next(file["content"] for file in result["files"] if file["path"].endswith(".js"))
        self.assertIn("new Blob", javascript)
        self.assertIn("data:image/png;base64", javascript)

    def test_bundles_worker_imports_into_the_blob(self) -> None:
        payload = self._project('import workerUrl from "./worker.ts?worker"; new Worker(workerUrl, { type: "module" })')
        payload["files"]["src/worker.ts"] = 'import { answer } from "./worker-lib"; self.postMessage(answer)'
        payload["files"]["src/worker-lib.ts"] = "export const answer = 42"

        result = run_cloud_builder(payload)

        self.assertEqual(result["status"], "ready", result["diagnostics"])
        javascript = next(file["content"] for file in result["files"] if file["path"].endswith(".js"))
        self.assertNotIn("worker-lib", javascript)
        self.assertIn("42", javascript)

    def test_runtime_bundles_pinned_dependencies_without_network_access(self) -> None:
        payload = {**self._project('import dayjs from "dayjs"; void dayjs'), "dependencies": {"dayjs": "1.11.13"}}

        result = run_cloud_builder(payload)

        self.assertEqual(result["status"], "ready", result["diagnostics"])
        html = next(file["content"] for file in result["files"] if file["path"] == "index.html")
        self.assertIn("script-src 'self'", html)
        self.assertNotIn("esm.sh", html)
        javascript = next(file["content"] for file in result["files"] if file["path"].endswith(".js"))
        self.assertNotIn('from"dayjs"', javascript)

    def test_source_contract_rejects_active_or_malformed_assets(self) -> None:
        for content, content_type in (("%%%", "image/png"), ("PGgxLz4=", "text/html")):
            payload = self._project("")
            payload["assets"] = {
                "assets/file.bin": {
                    "encoding": "base64",
                    "contentType": content_type,
                    "content": content,
                }
            }

            serializer = CanvasSourceProjectSerializer(data=payload)

            self.assertFalse(serializer.is_valid())
            self.assertIn("assets", serializer.errors)

    def test_rejects_artifact_content_that_does_not_match_manifest(self) -> None:
        result = {
            "contractVersion": 1,
            "status": "ready",
            "diagnostics": [],
            "files": [
                {
                    "path": "index.html",
                    "content": "tampered",
                    "contentHash": hashlib.sha256(b"safe").hexdigest(),
                    "sizeBytes": 4,
                }
            ],
            "manifest": {"entryHtml": "index.html", "assets": []},
        }

        with self.assertRaisesMessage(ValueError, "integrity"):
            validate_builder_output(result)

    def test_rejects_manifest_hash_that_does_not_match_emitted_file(self) -> None:
        content = "safe"
        digest = hashlib.sha256(content.encode()).hexdigest()
        result = {
            "contractVersion": 1,
            "status": "ready",
            "diagnostics": [],
            "files": [{"path": "index.html", "content": content, "contentHash": digest, "sizeBytes": 4}],
            "manifest": {
                "entryHtml": "index.html",
                "assets": [{"path": "index.html", "contentHash": "0" * 64, "sizeBytes": 4}],
            },
        }

        with self.assertRaisesMessage(ValueError, "manifest metadata"):
            validate_builder_output(result)

    @parameterized.expand(
        [
            ("path_traversal", "assets/../escape.js", False),
            ("absolute_path", "/etc/passwd", False),
            ("backslash", "assets\\bundle.js", False),
            ("control_character", "assets/bundle\n.js", False),
            ("beyond_source_charset", "assets/bundle name~.js", True),
        ]
    )
    def test_artifact_path_acceptance(self, _name: str, path: str, accepted: bool) -> None:
        content = "x"
        digest = hashlib.sha256(content.encode()).hexdigest()
        result = {
            "contractVersion": 1,
            "status": "ready",
            "diagnostics": [],
            "files": [
                {"path": "index.html", "content": content, "contentHash": digest, "sizeBytes": 1},
                {"path": path, "content": content, "contentHash": digest, "sizeBytes": 1},
            ],
            "manifest": {
                "entryHtml": "index.html",
                "assets": [
                    {"path": "index.html", "contentHash": digest, "sizeBytes": 1},
                    {"path": path, "contentHash": digest, "sizeBytes": 1},
                ],
            },
        }

        if accepted:
            validate_builder_output(result)
        else:
            with self.assertRaisesMessage(ValueError, "invalid artifact"):
                validate_builder_output(result)

    @patch("products.canvas.backend.build_service.subprocess.run")
    def test_builder_has_bounded_process_resources(self, run: Any) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = '{"contractVersion":1,"status":"failed","diagnostics":[]}'

        run_cloud_builder({"files": {}})

        args, kwargs = run.call_args
        self.assertEqual(args[0][1], "--max-old-space-size=256")
        self.assertEqual(kwargs["timeout"], 45)
        self.assertEqual(kwargs["env"], {"PATH": "/usr/local/bin:/usr/bin:/bin", "NODE_ENV": "production"})

    def test_runs_the_node_binary_resolved_from_the_worker_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / "node"
            stub.write_text(
                '#!/bin/sh\ncat > /dev/null\nprintf \'{"contractVersion":1,"status":"failed","diagnostics":[{"code":"stub_builder"}]}\'\n'
            )
            stub.chmod(0o755)

            with patch.dict(os.environ, {"PATH": directory}):
                result = run_cloud_builder({"files": {}})

        self.assertEqual(result["diagnostics"][0]["code"], "stub_builder")
