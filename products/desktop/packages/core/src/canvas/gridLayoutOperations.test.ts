import { describe, expect, it } from "vitest";
import { applyLayoutOperations } from "./gridLayoutOperations";
import type { CanvasLayout, LayoutOperation } from "./gridLayoutSchemas";

const LAYOUT: CanvasLayout = {
  schemaVersion: 1,
  grid: { columns: 6, rowHeight: 96, gap: 8 },
  placements: [
    { id: "p1", status: "live", x: 0, y: 0, w: 2, h: 2 },
    { id: "p2", status: "pending", x: 2, y: 0, w: 1, h: 1 },
  ],
};

describe("applyLayoutOperations", () => {
  // What a surface shows between a gesture and its patch answering, so each op
  // has to land the same way the server lands it.
  it.each([
    [
      "moves a placement",
      [
        {
          op: "update_placement",
          id: "p1",
          changes: { x: 3, y: 1 },
        },
      ] satisfies LayoutOperation[],
      { p1: { x: 3, y: 1, w: 2, h: 2 }, p2: { x: 2, y: 0, w: 1, h: 1 } },
    ],
    [
      "removes a placement",
      [{ op: "remove_placement", id: "p2" }] satisfies LayoutOperation[],
      { p1: { x: 0, y: 0, w: 2, h: 2 } },
    ],
    [
      "adds a placement",
      [
        {
          op: "add_placement",
          placement: { id: "p3", status: "pending", x: 4, y: 0, w: 2, h: 2 },
        },
      ] satisfies LayoutOperation[],
      {
        p1: { x: 0, y: 0, w: 2, h: 2 },
        p2: { x: 2, y: 0, w: 1, h: 1 },
        p3: { x: 4, y: 0, w: 2, h: 2 },
      },
    ],
  ])("%s", (_name, operations, expected) => {
    const result = applyLayoutOperations(LAYOUT, operations);
    expect(
      Object.fromEntries(
        result.placements.map(({ id, x, y, w, h }) => [id, { x, y, w, h }]),
      ),
    ).toEqual(expected);
  });

  it("leaves the document it was given untouched", () => {
    applyLayoutOperations(LAYOUT, [
      { op: "remove_placement", id: "p1" },
      { op: "set_grid", grid: { columns: 12, rowHeight: 96, gap: 8 } },
    ]);
    expect(LAYOUT.placements).toHaveLength(2);
    expect(LAYOUT.grid.columns).toBe(6);
  });
});
