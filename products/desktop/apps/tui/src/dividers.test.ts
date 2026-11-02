import { describe, expect, it } from "vitest";
import { dividerGlyphs } from "./dividers";
import type { LayoutNode } from "./layout";

const pane = (id: string): LayoutNode => ({ kind: "pane", id, taskId: null });
const split = (
  direction: "row" | "column",
  ...children: LayoutNode[]
): LayoutNode => ({ kind: "split", direction, children });

// The chat area's divider cells, with the sidebar's edge as the first column.
const draw = (root: LayoutNode, width: number, height: number): string[] => {
  const glyph = dividerGlyphs(root, width, height);
  return Array.from({ length: height }, (_, y) =>
    Array.from({ length: width + 1 }, (_, x) => glyph(x - 1, y)).join(""),
  );
};

describe("dividerGlyphs", () => {
  it.each([
    [
      "a row split into a stack",
      split("row", pane("a"), split("column", pane("b"), pane("c"))),
      ["│    │    ", "│    │    ", "│    ├────", "│    │    ", "│    │    "],
    ],
    [
      "a stack under a row split",
      split("column", split("row", pane("a"), pane("b")), pane("c")),
      ["│    │    ", "│    │    ", "├────┴────", "│         ", "│         "],
    ],
    [
      "a stack over a row split",
      split("column", pane("a"), split("row", pane("b"), pane("c"))),
      ["│         ", "│         ", "├────┬────", "│    │    ", "│    │    "],
    ],
    [
      "two stacks side by side",
      split(
        "row",
        split("column", pane("a"), pane("b")),
        split("column", pane("c"), pane("d")),
      ),
      ["│    │    ", "│    │    ", "├────┼────", "│    │    ", "│    │    "],
    ],
  ])("joins the lines of %s", (_, root, expected) => {
    expect(draw(root, 9, 5)).toEqual(expected);
  });
});
