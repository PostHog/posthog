import { describe, expect, it } from "vitest";
import { arrowHead, hitShape, type Shape, shapeBBox } from "./shapes";

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
});
