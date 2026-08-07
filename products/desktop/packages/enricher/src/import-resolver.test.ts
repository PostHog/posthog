import * as fs from "node:fs";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { PostHogDetector } from "./detector.js";

const GRAMMARS_DIR = path.join(__dirname, "..", "grammars");
const hasGrammars = fs.existsSync(
  path.join(GRAMMARS_DIR, "tree-sitter-javascript.wasm"),
);
const describeWithGrammars = hasGrammars ? describe : describe.skip;

describeWithGrammars("findImports", () => {
  let detector: PostHogDetector;
  let workDir: string;
  let callerTs: string;
  let callerPy: string;

  beforeAll(() => {
    detector = new PostHogDetector();
    workDir = mkdtempSync(path.join(tmpdir(), "enricher-imports-"));

    // JS/TS sibling modules
    writeFileSync(
      path.join(workDir, "telemetry.ts"),
      "export function track() {}\nexport default function dflt() {}\n",
    );
    writeFileSync(path.join(workDir, "sibling.js"), "module.exports = {};\n");
    mkdirSync(path.join(workDir, "helpers"), { recursive: true });
    writeFileSync(
      path.join(workDir, "helpers", "index.ts"),
      "export function helperTrack() {}\n",
    );

    // Python sibling module
    writeFileSync(
      path.join(workDir, "tel.py"),
      "def track(event_name):\n    pass\n",
    );
    // Python package dir
    mkdirSync(path.join(workDir, "pkg"), { recursive: true });
    writeFileSync(
      path.join(workDir, "pkg", "__init__.py"),
      "def helper():\n    pass\n",
    );

    callerTs = path.join(workDir, "caller.ts");
    callerPy = path.join(workDir, "caller.py");
  });

  afterAll(() => {
    fs.rmSync(workDir, { recursive: true, force: true });
  });

  test("named JS import resolves to .ts neighbor", async () => {
    const src = `import { track } from "./telemetry";\ntrack("x");`;
    const edges = await detector.findImports(src, "typescript", callerTs);
    expect(edges).toHaveLength(1);
    expect(edges[0].localName).toBe("track");
    expect(edges[0].importedName).toBe("track");
    expect(edges[0].resolvedAbsPath).toBe(path.join(workDir, "telemetry.ts"));
    expect(edges[0].isDefault).toBeFalsy();
    expect(edges[0].isNamespace).toBeFalsy();
  });

  test("aliased named import records both names", async () => {
    const src = `import { track as t } from "./telemetry";`;
    const edges = await detector.findImports(src, "typescript", callerTs);
    const edge = edges.find((e) => e.localName === "t");
    expect(edge).toBeDefined();
    expect(edge?.importedName).toBe("track");
  });

  test("default import", async () => {
    const src = `import track from "./telemetry";`;
    const edges = await detector.findImports(src, "typescript", callerTs);
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({
      localName: "track",
      importedName: "default",
      isDefault: true,
    });
  });

  test("namespace import", async () => {
    const src = `import * as tel from "./telemetry";`;
    const edges = await detector.findImports(src, "typescript", callerTs);
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({
      localName: "tel",
      importedName: "*",
      isNamespace: true,
    });
  });

  test("index.ts in folder resolves", async () => {
    const src = `import { helperTrack } from "./helpers";`;
    const edges = await detector.findImports(src, "typescript", callerTs);
    expect(edges[0].resolvedAbsPath).toBe(
      path.join(workDir, "helpers", "index.ts"),
    );
  });

  test("missing target → null", async () => {
    const src = `import { x } from "./missing";`;
    const edges = await detector.findImports(src, "typescript", callerTs);
    expect(edges[0].resolvedAbsPath).toBeNull();
  });

  test("non-relative specifier is ignored", async () => {
    const src = `import { capture } from "posthog-js";\nimport foo from "@scope/pkg";`;
    const edges = await detector.findImports(src, "typescript", callerTs);
    expect(edges).toEqual([]);
  });

  test(".js extension also probes", async () => {
    const src = `import sib from "./sibling";`;
    const edges = await detector.findImports(src, "typescript", callerTs);
    expect(edges[0].resolvedAbsPath).toBe(path.join(workDir, "sibling.js"));
  });

  test("Python: relative from-import resolves to .py", async () => {
    const src = `from .tel import track\n`;
    const edges = await detector.findImports(src, "python", callerPy);
    expect(edges).toHaveLength(1);
    expect(edges[0].localName).toBe("track");
    expect(edges[0].importedName).toBe("track");
    expect(edges[0].resolvedAbsPath).toBe(path.join(workDir, "tel.py"));
  });

  test("Python: aliased from-import", async () => {
    const src = `from .tel import track as t\n`;
    const edges = await detector.findImports(src, "python", callerPy);
    expect(edges[0]).toMatchObject({
      localName: "t",
      importedName: "track",
    });
  });

  test("Python: package __init__ resolves", async () => {
    const src = `from .pkg import helper\n`;
    const edges = await detector.findImports(src, "python", callerPy);
    expect(edges[0].resolvedAbsPath).toBe(
      path.join(workDir, "pkg", "__init__.py"),
    );
  });

  test("Go import query is absent — returns empty", async () => {
    const src = `import "fmt"`;
    const edges = await detector.findImports(
      src,
      "go",
      path.join(workDir, "caller.go"),
    );
    expect(edges).toEqual([]);
  });
});
