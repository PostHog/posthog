import { describe, expect, it } from "vitest";
import {
  hasDraggedFar,
  marqueeSpan,
  mergeMarqueeSelection,
  rowsInMarquee,
} from "./marquee";

const rows = [
  { id: "a", top: 0, bottom: 20 },
  { id: "b", top: 20, bottom: 40 },
  { id: "c", top: 40, bottom: 60 },
];

describe("hasDraggedFar", () => {
  it.each([
    { name: "a still press", dx: 0, dy: 0, expected: false },
    { name: "a shaky click", dx: 1, dy: 2, expected: false },
    { name: "a vertical drag", dx: 0, dy: 6, expected: true },
    { name: "an upward drag", dx: 0, dy: -6, expected: true },
    { name: "a sideways drag", dx: 9, dy: 0, expected: true },
  ])("reads $name as $expected", ({ dx, dy, expected }) => {
    expect(hasDraggedFar(dx, dy)).toBe(expected);
  });
});

describe("marqueeSpan", () => {
  it.each([
    { name: "downward", origin: 10, current: 50 },
    { name: "upward", origin: 50, current: 10 },
  ])("normalizes a $name drag", ({ origin, current }) => {
    expect(marqueeSpan(origin, current)).toEqual({ top: 10, bottom: 50 });
  });
});

describe("rowsInMarquee", () => {
  it("takes every row the span crosses", () => {
    expect(rowsInMarquee({ top: 10, bottom: 45 }, rows)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("takes a row the span only grazes", () => {
    expect(rowsInMarquee({ top: 55, bottom: 80 }, rows)).toEqual(["c"]);
  });

  it("takes nothing when the span misses every row", () => {
    expect(rowsInMarquee({ top: 70, bottom: 90 }, rows)).toEqual([]);
  });
});

describe("mergeMarqueeSelection", () => {
  it("replaces the previous selection by default", () => {
    expect(mergeMarqueeSelection(["a", "b"], ["c"], false)).toEqual(["c"]);
  });

  it("keeps the previous selection when additive", () => {
    expect(mergeMarqueeSelection(["a"], ["b", "c"], true)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("does not duplicate a row already selected", () => {
    expect(mergeMarqueeSelection(["a", "b"], ["b", "c"], true)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });
});
