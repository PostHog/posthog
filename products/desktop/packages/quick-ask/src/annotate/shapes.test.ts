import { beforeAll, describe, expect, it, vi } from "vitest";
import {
  arrowHead,
  hitShape,
  type Shape,
  shapeBBox,
  textLines,
} from "./shapes";

// Text measuring goes through a module-level canvas context; give the node
// environment a deterministic 10px-per-character measurer.
beforeAll(() => {
  vi.stubGlobal("document", {
    createElement: () => ({
      getContext: () => ({
        font: "",
        measureText: (text: string) => ({ width: text.length * 10 }),
      }),
    }),
  });
});

describe("annotator shape geometry", () => {
  // A long horizontal arrow: the head is 26px deep and its wings flare
  // vertically past the zero-height from->to box.
  const arrow: Shape = {
    kind: "arrow",
    from: { x: 0, y: 50 },
    to: { x: 200, y: 50 },
    color: "#fff",
  };

  it("includes the arrowhead wings in the bounding box", () => {
    const { wings } = arrowHead(arrow.from, arrow.to);
    const box = shapeBBox(arrow);
    for (const wing of wings) {
      expect(wing.y).toBeGreaterThanOrEqual(box.y);
      expect(wing.y).toBeLessThanOrEqual(box.y + box.h);
    }
    // The shaft alone would give a zero-height box.
    expect(box.h).toBeGreaterThan(0);
  });

  it("hits a click on an arrowhead wing, not just the shaft", () => {
    const { wings } = arrowHead(arrow.from, arrow.to);
    // The upper wing tip sits ~11px off the shaft, beyond the 6px slack.
    expect(Math.abs(wings[0].y - 50)).toBeGreaterThan(6);
    expect(hitShape(arrow, wings[0])).toBe(true);
    expect(hitShape(arrow, wings[1])).toBe(true);
    // Well off the head stays a miss.
    expect(hitShape(arrow, { x: 200, y: 80 })).toBe(false);
  });

  it("breaks a word wider than the wrap width instead of overflowing", () => {
    // 12 characters at 10px each against a 40px width: no line may exceed
    // the width, and nothing may be dropped.
    const lines = textLines("abcdefghijkl", 17, 40);
    expect(lines).toEqual(["abcd", "efgh", "ijkl"]);
  });

  it("still wraps at spaces before resorting to breaking words", () => {
    expect(textLines("ab cd efghijkl", 17, 50)).toEqual([
      "ab cd",
      "efghi",
      "jkl",
    ]);
  });

  it("keeps a click-only pen stroke selectable at its point", () => {
    const dot: Shape = {
      kind: "pen",
      points: [{ x: 30, y: 40 }],
      color: "#fff",
    };
    expect(hitShape(dot, { x: 33, y: 42 })).toBe(true);
    expect(hitShape(dot, { x: 45, y: 40 })).toBe(false);
    expect(shapeBBox(dot)).toEqual({ x: 30, y: 40, w: 0, h: 0 });
  });

  it("gives an empty pen shape a finite bounding box", () => {
    const empty: Shape = { kind: "pen", points: [], color: "#fff" };
    expect(shapeBBox(empty)).toEqual({ x: 0, y: 0, w: 0, h: 0 });
    expect(hitShape(empty, { x: 0, y: 0 })).toBe(false);
  });
});
