import { describe, expect, it } from "vitest";
import {
  CANVAS_COMPONENT_PATH,
  CANVAS_ENTRY_HTML,
  type CanvasSourceProject,
  canvasSourcePathProblem,
  canvasSourceProjectSchema,
  DEFAULT_CANVAS_CAPABILITIES,
  hasCanvasErrors,
  MAX_CANVAS_FILE_BYTES,
  MAX_CANVAS_SOURCE_FILES,
  validateCanvasSourceProject,
} from "./canvas-contracts";

function project(
  overrides: Partial<CanvasSourceProject> = {},
): CanvasSourceProject {
  return {
    schemaVersion: 1,
    files: {
      [CANVAS_ENTRY_HTML]: "<!doctype html><html></html>",
      [CANVAS_COMPONENT_PATH]: "export default () => null;",
    },
    entryHtml: CANVAS_ENTRY_HTML,
    dependencies: { react: "19.0.0" },
    canvasSdkVersion: "0.1.0",
    capabilities: DEFAULT_CANVAS_CAPABILITIES,
    ...overrides,
  };
}

describe("canvas contracts", () => {
  it("accepts a well-formed source project with no diagnostics", () => {
    const candidate = project();
    expect(canvasSourceProjectSchema.parse(candidate)).toEqual(candidate);
    expect(validateCanvasSourceProject(candidate)).toEqual([]);
  });

  it.each([
    ["unknown schema version", { schemaVersion: 2 }],
    ["non-index entry html", { entryHtml: "main.html" }],
  ])("schema rejects %s", (_name, overrides) => {
    const candidate = { ...project(), ...overrides };
    expect(canvasSourceProjectSchema.safeParse(candidate).success).toBe(false);
  });

  it.each([
    ["", false],
    ["/etc/passwd", false],
    ["../escape.tsx", false],
    ["src/../escape.tsx", false],
    ["src\\win.tsx", false],
    ["src//double.ts", false],
    ["src/ok-file_2.tsx", true],
    ["assets/@scope/logo.svg", true],
  ])("path %j valid=%s", (path, valid) => {
    expect(canvasSourcePathProblem(path) === null).toBe(valid);
  });

  it.each([
    [
      "a traversal path",
      project({
        files: { ...project().files, "../escape.tsx": "x" },
      }),
      "invalid_path",
    ],
    [
      "a missing entry file",
      project({ files: { [CANVAS_COMPONENT_PATH]: "x" } }),
      "missing_entry",
    ],
    [
      "an oversized file",
      project({
        files: {
          ...project().files,
          "src/big.ts": "a".repeat(MAX_CANVAS_FILE_BYTES + 1),
        },
      }),
      "file_too_large",
    ],
    [
      "too many files",
      project({
        files: {
          ...project().files,
          ...Object.fromEntries(
            Array.from({ length: MAX_CANVAS_SOURCE_FILES }, (_, i) => [
              `src/f${i}.ts`,
              "x",
            ]),
          ),
        },
      }),
      "too_many_files",
    ],
  ])("flags %s as an error", (_name, candidate, code) => {
    const diagnostics = validateCanvasSourceProject(candidate);
    expect(hasCanvasErrors(diagnostics)).toBe(true);
    expect(diagnostics.map((d) => d.code)).toContain(code);
  });

  it("treats warning-only diagnostics as publishable", () => {
    expect(
      hasCanvasErrors([
        { severity: "warning", code: "network_fetch", message: "…" },
      ]),
    ).toBe(false);
  });
});
