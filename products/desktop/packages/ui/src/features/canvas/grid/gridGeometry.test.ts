import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import { describe, expect, it } from "vitest";
import {
  cellFromPoint,
  clampRect,
  collides,
  rectFromCells,
} from "./gridGeometry";

function placement(overrides: Partial<GridPlacement>): GridPlacement {
  return { id: "p1", status: "pending", x: 0, y: 0, w: 2, h: 1, ...overrides };
}

describe("gridGeometry", () => {
  it.each([
    ["separate columns", { x: 2, y: 0, w: 2, h: 1 }, false],
    ["exact overlap", { x: 0, y: 0, w: 2, h: 1 }, true],
    ["partial overlap", { x: 1, y: 0, w: 2, h: 1 }, true],
    ["touching edges do not overlap", { x: 0, y: 1, w: 2, h: 1 }, false],
  ])("collides: %s", (_name, rect, expected) => {
    expect(collides(rect, [placement({})])).toBe(expected);
  });

  it("collides ignores the placement being moved", () => {
    expect(collides({ x: 0, y: 0, w: 2, h: 1 }, [placement({})], "p1")).toBe(
      false,
    );
  });

  it.each([
    [
      "oversized width shrinks to grid",
      { x: 0, y: 0, w: 9, h: 1 },
      { x: 0, y: 0, w: 6, h: 1 },
    ],
    [
      "right overflow slides left",
      { x: 5, y: 0, w: 2, h: 1 },
      { x: 4, y: 0, w: 2, h: 1 },
    ],
    [
      "negative origin clamps to zero",
      { x: -1, y: -2, w: 1, h: 1 },
      { x: 0, y: 0, w: 1, h: 1 },
    ],
    [
      "zero size becomes one cell",
      { x: 0, y: 0, w: 0, h: 0 },
      { x: 0, y: 0, w: 1, h: 1 },
    ],
  ])("clampRect: %s", (_name, rect, expected) => {
    expect(clampRect(rect, 6)).toEqual(expected);
  });

  it("cellFromPoint maps pointer positions to cells including the gap", () => {
    const grid = { columns: 6, rowHeight: 96, gap: 8 };
    const surface = { left: 0, top: 0, width: 616 };
    expect(cellFromPoint(0, 0, surface, grid)).toEqual({ col: 0, row: 0 });
    expect(cellFromPoint(110, 105, surface, grid)).toEqual({ col: 1, row: 1 });
    expect(cellFromPoint(9999, 0, surface, grid)).toEqual({ col: 5, row: 0 });
  });

  it("rectFromCells normalizes a drag in any direction", () => {
    expect(rectFromCells({ col: 3, row: 2 }, { col: 1, row: 4 })).toEqual({
      x: 1,
      y: 2,
      w: 3,
      h: 3,
    });
  });
});
