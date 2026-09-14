import { describe, expect, it } from "vitest";
import {
  BRAINROT_CELL,
  makeCanvasCellValue,
  makeTerminalCellValue,
} from "./grid";
import { type PlacementInput, planCommandCenterPlacement } from "./placement";

/**
 * Defaults every id on the grid to a task that still exists, which is the
 * ordinary case. Cases about deleted tasks pass `liveTaskIds` themselves.
 */
function plan(input: Omit<PlacementInput, "liveTaskIds">) {
  return planCommandCenterPlacement({
    ...input,
    liveTaskIds: new Set(input.cells.filter((c): c is string => c != null)),
  });
}

describe("planCommandCenterPlacement", () => {
  it("fills empty tiles in order without touching the layout", () => {
    const result = plan({
      cells: ["a", null, null, null],
      layout: "2x2",
      taskIds: ["b", "c"],
    });
    expect(result.layout).toBe("2x2");
    expect(result.cells).toEqual(["a", "b", "c", null]);
    expect(result.placed).toEqual(["b", "c"]);
    expect(result.overflow).toEqual([]);
  });

  it("grows the layout when the batch outgrows the empty tiles", () => {
    const result = plan({
      cells: ["a", "b", "c", null],
      layout: "2x2",
      taskIds: ["d", "e", "f"],
    });
    expect(result.layout).toBe("3x2");
    // Growing a column moves rows, so b stays beside a and c stays on row two.
    expect(result.cells).toEqual(["a", "b", "d", "c", "e", "f"]);
    expect(result.placed).toEqual(["d", "e", "f"]);
    expect(result.overflow).toEqual([]);
  });

  it("reports ids that do not fit even at the 3x3 ceiling", () => {
    const result = plan({
      cells: Array.from({ length: 9 }, (_, i) => `t${i}`),
      layout: "3x3",
      taskIds: ["new-1", "new-2"],
    });
    expect(result.layout).toBe("3x3");
    expect(result.placed).toEqual([]);
    expect(result.overflow).toEqual(["new-1", "new-2"]);
  });

  it("leaves ids already on the grid where they are", () => {
    const result = plan({
      cells: ["a", null, null, null],
      layout: "2x2",
      taskIds: ["a", "b"],
    });
    expect(result.cells).toEqual(["a", "b", null, null]);
    expect(result.alreadyPresent).toEqual(["a"]);
    expect(result.placed).toEqual(["b"]);
  });

  it("deduplicates the batch", () => {
    const result = plan({
      cells: [null, null, null, null],
      layout: "2x2",
      taskIds: ["a", "a", "b"],
    });
    expect(result.cells).toEqual(["a", "b", null, null]);
    expect(result.placed).toEqual(["a", "b"]);
  });

  it.each([
    { name: "brainrot", cell: BRAINROT_CELL },
    { name: "terminal", cell: makeTerminalCellValue("abc123") },
    { name: "canvas", cell: makeCanvasCellValue("canvas-1") },
  ])("never overwrites the $name sentinel", ({ cell }) => {
    // Sentinels are not tasks, so they are absent from every live task list.
    const result = planCommandCenterPlacement({
      cells: [cell, null],
      layout: "2x1",
      taskIds: ["a"],
      liveTaskIds: new Set<string>(),
    });
    expect(result.cells).toEqual([cell, "a"]);
  });

  it("reuses a cell whose task was deleted, which the grid draws empty", () => {
    const result = planCommandCenterPlacement({
      cells: ["gone", "b"],
      layout: "2x1",
      taskIds: ["c"],
      liveTaskIds: new Set(["b"]),
    });
    expect(result.layout).toBe("2x1");
    expect(result.cells).toEqual(["c", "b"]);
    expect(result.overflow).toEqual([]);
  });

  it("holds every cell while the task list is unknown", () => {
    const cells = Array.from({ length: 9 }, (_, i) => `t${i}`);
    const result = planCommandCenterPlacement({
      cells,
      layout: "3x3",
      taskIds: ["new"],
      liveTaskIds: null,
    });
    expect(result.cells).toEqual(cells);
    expect(result.overflow).toEqual(["new"]);
  });

  it("is a no-op for an empty batch", () => {
    const result = plan({
      cells: ["a", null],
      layout: "2x1",
      taskIds: [],
    });
    expect(result).toEqual({
      layout: "2x1",
      cells: ["a", null],
      placed: [],
      overflow: [],
      alreadyPresent: [],
    });
  });
});
