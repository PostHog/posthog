import {
  canvasRuntimeImportMap,
  createCanvasStarterProject,
  MAX_CANVAS_ARTIFACT_FILE_BYTES,
} from "./canvas-build-contract";
import {
  CANVAS_ENTRY_HTML,
  type CanvasSourceProject,
} from "./canvas-contracts";

// Contract fixtures every canvas build adapter (workspace-server local build,
// cloud build) must produce the same outcome for. Running the identical
// fixtures through each adapter catches toolchain drift before a publish
// produces different diagnostics than the preview that preceded it.

export interface CanvasBuildContractFixture {
  name: string;
  project: CanvasSourceProject;
  expected: {
    status: "ready" | "failed";
    /** Diagnostic codes that must be present (subset match). */
    diagnosticCodes?: string[];
  };
}

function project(
  files: Record<string, string>,
  dependencies: Record<string, string> = {},
): CanvasSourceProject {
  return {
    schemaVersion: 1,
    files,
    entryHtml: CANVAS_ENTRY_HTML,
    dependencies,
    canvasSdkVersion: "0.1.0",
    capabilities: {
      posthog: { insights: [], inlineQueries: false, captureEvents: [] },
      network: { origins: [] },
    },
  };
}

const HTML_SHELL = (body: string, head = "") => `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
${head}
  </head>
  <body>
${body}
  </body>
</html>
`;

const REACT_DEPS = {
  react: "19.0.0",
  "react-dom": "19.0.0",
  "@posthog/quill": "0.3.0-beta.18",
};

export const CANVAS_BUILD_CONTRACT_FIXTURES: CanvasBuildContractFixture[] = [
  {
    name: "neutral starter project",
    project: createCanvasStarterProject(),
    expected: { status: "ready" },
  },
  {
    name: "react + quill application",
    project: project(
      {
        [CANVAS_ENTRY_HTML]: HTML_SHELL(
          '    <div id="root"></div>\n    <script type="module" src="/src/main.tsx"></script>',
        ),
        "src/main.tsx": [
          'import { createRoot } from "react-dom/client";',
          'import { App } from "./App";',
          'createRoot(document.getElementById("root")!).render(<App />);',
        ].join("\n"),
        "src/App.tsx": [
          'import { useState } from "react";',
          "export function App() {",
          "  const [count, setCount] = useState(0);",
          "  return <button onClick={() => setCount((c) => c + 1)}>clicked {count}</button>;",
          "}",
        ].join("\n"),
      },
      REACT_DEPS,
    ),
    expected: { status: "ready" },
  },
  {
    name: "semantic html document",
    project: project({
      [CANVAS_ENTRY_HTML]: HTML_SHELL(
        [
          "    <article>",
          "      <h1>Quarterly notes</h1>",
          "      <p>A document canvas needs no framework.</p>",
          "    </article>",
          '    <script type="module" src="/src/main.ts"></script>',
        ].join("\n"),
        '    <link rel="stylesheet" href="/src/style.css" />',
      ),
      "src/main.ts":
        'document.querySelector("article")?.classList.add("ready");\nexport {};',
      "src/style.css": "article { max-width: 60ch; margin: 0 auto; }",
    }),
    expected: { status: "ready" },
  },
  {
    name: "webgl experience on raw browser APIs",
    project: project({
      [CANVAS_ENTRY_HTML]: HTML_SHELL(
        '    <canvas id="scene"></canvas>\n    <script type="module" src="/src/main.ts"></script>',
      ),
      "src/main.ts": [
        'const canvas = document.getElementById("scene") as HTMLCanvasElement;',
        'const gl = canvas.getContext("webgl2");',
        "function frame(t: number) {",
        "  if (gl) {",
        "    gl.clearColor(Math.sin(t / 1000) ** 2, 0.2, 0.4, 1);",
        "    gl.clear(gl.COLOR_BUFFER_BIT);",
        "  }",
        "  requestAnimationFrame(frame);",
        "}",
        "requestAnimationFrame(frame);",
        "export {};",
      ].join("\n"),
    }),
    expected: { status: "ready" },
  },
  {
    name: "asset imports (svg data-url + json)",
    project: project({
      [CANVAS_ENTRY_HTML]: HTML_SHELL(
        '    <div id="root"></div>\n    <script type="module" src="/src/main.ts"></script>',
      ),
      "src/main.ts": [
        'import logo from "./logo.svg";',
        'import config from "./config.json";',
        'const img = document.createElement("img");',
        "img.src = logo;",
        "img.alt = config.title;",
        'document.getElementById("root")?.append(img);',
        "export {};",
      ].join("\n"),
      "src/logo.svg":
        '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="#f54d00"/></svg>',
      "src/config.json": '{ "title": "hedgehog" }',
    }),
    expected: { status: "ready" },
  },
  {
    name: "import of a non-admitted package",
    project: project(
      {
        [CANVAS_ENTRY_HTML]: HTML_SHELL(
          '    <script type="module" src="/src/main.ts"></script>',
        ),
        "src/main.ts":
          'import _ from "lodash";\nconsole.log(_.chunk([1, 2, 3], 2));\nexport {};',
      },
      { lodash: "4.17.21" },
    ),
    expected: {
      status: "failed",
      diagnosticCodes: ["dependency_not_admitted"],
    },
  },
  {
    name: "undeclared bare import",
    project: project({
      [CANVAS_ENTRY_HTML]: HTML_SHELL(
        '    <script type="module" src="/src/main.ts"></script>',
      ),
      "src/main.ts": 'import _ from "lodash";\nconsole.log(_);\nexport {};',
    }),
    expected: { status: "failed", diagnosticCodes: ["import_not_declared"] },
  },
  {
    name: "typescript syntax error",
    project: project({
      [CANVAS_ENTRY_HTML]: HTML_SHELL(
        '    <script type="module" src="/src/main.ts"></script>',
      ),
      "src/main.ts": "const broken = {;\nexport {};",
    }),
    expected: { status: "failed", diagnosticCodes: ["bundle_error"] },
  },
  {
    name: "missing module entry in html",
    project: project({
      [CANVAS_ENTRY_HTML]: HTML_SHELL(
        '    <script type="module" src="/src/missing.ts"></script>',
      ),
      "src/main.ts": "export {};",
    }),
    expected: { status: "failed", diagnosticCodes: ["entry_not_found"] },
  },
  {
    name: "oversized emitted output",
    project: project({
      [CANVAS_ENTRY_HTML]: HTML_SHELL(
        '    <script type="module" src="/src/main.ts"></script>',
      ),
      // Three modules, each under the per-source-file limit, bundle into one
      // chunk beyond the per-artifact-file budget — the output scan must trip
      // even though every input passed stage-1 validation.
      "src/main.ts": [
        'import { a } from "./a";',
        'import { b } from "./b";',
        'import { c } from "./c";',
        "console.log(a.length + b.length + c.length);",
        "export {};",
      ].join("\n"),
      "src/a.ts": `export const a = "${"a".repeat(Math.floor(MAX_CANVAS_ARTIFACT_FILE_BYTES * 0.45))}";`,
      "src/b.ts": `export const b = "${"b".repeat(Math.floor(MAX_CANVAS_ARTIFACT_FILE_BYTES * 0.45))}";`,
      "src/c.ts": `export const c = "${"c".repeat(Math.floor(MAX_CANVAS_ARTIFACT_FILE_BYTES * 0.45))}";`,
    }),
    expected: { status: "failed", diagnosticCodes: ["artifact_too_large"] },
  },
];

/** Runtime import-map entries a ready react-fixture artifact must resolve. */
export const CANVAS_FIXTURE_REACT_IMPORTS = Object.keys(
  canvasRuntimeImportMap(REACT_DEPS),
);
