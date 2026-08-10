import { describe, expect, it } from "vitest";
import { BRAINROT_CELL, makeTerminalCellValue } from "./grid";
import { planCommandCenterPlacement } from "./placement";

describe("planCommandCenterPlacement", () => {
  it("fills empty tiles in order without touching the layout", () => {
    const plan = planCommandCenterPlacement({
      cells: ["a", null, null, null],
      layout: "2x2",
      taskIds: ["b", "c"],
    });
    expect(plan.layout).toBe("2x2");
    expect(plan.cells).toEqual(["a", "b", "c", null]);
    expect(plan.placed).toEqual(["b", "c"]);
    expect(plan.overflow).toEqual([]);
  });

  it("grows the layout when the batch outgrows the empty tiles", () => {
    const plan = planCommandCenterPlacement({
      cells: ["a", "b", "c", null],
      layout: "2x2",
      taskIds: ["d", "e", "f"],
    });
    expect(plan.layout).toBe("3x2");
    // Growing a column moves rows, so b stays beside a and c stays on row two.
    expect(plan.cells).toEqual(["a", "b", "d", "c", "e", "f"]);
    expect(plan.placed).toEqual(["d", "e", "f"]);
    expect(plan.overflow).toEqual([]);
  });

  it("reports ids that do not fit even at the 3x3 ceiling", () => {
    const plan = planCommandCenterPlacement({
      cells: Array.from({ length: 9 }, (_, i) => `t${i}`),
      layout: "3x3",
      taskIds: ["new-1", "new-2"],
    });
    expect(plan.layout).toBe("3x3");
    expect(plan.placed).toEqual([]);
    expect(plan.overflow).toEqual(["new-1", "new-2"]);
  });

  it("leaves ids already on the grid where they are", () => {
    const plan = planCommandCenterPlacement({
      cells: ["a", null, null, null],
      layout: "2x2",
      taskIds: ["a", "b"],
    });
    expect(plan.cells).toEqual(["a", "b", null, null]);
    expect(plan.alreadyPresent).toEqual(["a"]);
    expect(plan.placed).toEqual(["b"]);
  });

  it("deduplicates the batch", () => {
    const plan = planCommandCenterPlacement({
      cells: [null, null, null, null],
      layout: "2x2",
      taskIds: ["a", "a", "b"],
    });
    expect(plan.cells).toEqual(["a", "b", null, null]);
    expect(plan.placed).toEqual(["a", "b"]);
  });

  it.each([
    { name: "brainrot", cell: BRAINROT_CELL },
    { name: "terminal", cell: makeTerminalCellValue("abc123") },
  ])("never overwrites the $name sentinel", ({ cell }) => {
    const plan = planCommandCenterPlacement({
      cells: [cell, null],
      layout: "2x1",
      taskIds: ["a"],
    });
    expect(plan.cells).toEqual([cell, "a"]);
  });

  it("is a no-op for an empty batch", () => {
    const plan = planCommandCenterPlacement({
      cells: ["a", null],
      layout: "2x1",
      taskIds: [],
    });
    expect(plan).toEqual({
      layout: "2x1",
      cells: ["a", null],
      placed: [],
      overflow: [],
      alreadyPresent: [],
    });
  });
});
