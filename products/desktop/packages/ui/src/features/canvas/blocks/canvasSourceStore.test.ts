import type { CanvasSourceProject } from "@posthog/core/canvas/dashboardSchemas";
import { beforeEach, describe, expect, it } from "vitest";
import { isSourceDirty, useCanvasSourceStore } from "./canvasSourceStore";

const CANVAS = "canvas-1";
const PROJECT = {
  schemaVersion: 1,
  entryHtml: "index.html",
  files: { "src/canvas.tsx": "saved" },
  dependencies: {},
} as unknown as CanvasSourceProject;

function entry() {
  const current = useCanvasSourceStore.getState().entries[CANVAS];
  if (!current) throw new Error("missing entry");
  return current;
}

describe("canvasSourceStore conflicts", () => {
  beforeEach(() => {
    const store = useCanvasSourceStore.getState();
    store.load(CANVAS, PROJECT, "v1");
    store.apply(CANVAS, { "src/canvas.tsx": "local edit" });
    store.setConflict(CANVAS, "v2");
  });

  it.each([
    {
      keepLocal: true,
      base: "v2",
      files: { "src/canvas.tsx": "local edit" },
      dirty: true,
    },
    {
      keepLocal: false,
      base: "v1",
      files: { "src/canvas.tsx": "saved" },
      dirty: false,
    },
  ])(
    "keepLocal=$keepLocal publishes over v2 only when chosen",
    ({ keepLocal, base, files, dirty }) => {
      useCanvasSourceStore.getState().resolveConflict(CANVAS, keepLocal);
      expect(entry().conflict).toBeNull();
      expect(entry().baseVersionId).toBe(base);
      expect(entry().files).toEqual(files);
      expect(isSourceDirty(entry())).toBe(dirty);
    },
  );

  it("drops undo history when a newer version loads", () => {
    useCanvasSourceStore.getState().load(CANVAS, PROJECT, "v2");
    expect(entry().past).toEqual([]);
  });
});
