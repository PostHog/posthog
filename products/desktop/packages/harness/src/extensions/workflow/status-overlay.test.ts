import { describe, expect, it } from "vitest";
import { clampScroll, overlayBodyRows, viewportLines } from "./status-overlay";

describe("workflow status overlay viewport helpers", () => {
  it.each([
    ["clamps before the first row", -3, 10, 4, 0],
    ["keeps a valid offset", 3, 10, 4, 3],
    ["clamps after the last complete page", 99, 10, 4, 6],
    ["handles a viewport larger than content", 2, 3, 8, 0],
  ])("%s", (_name, offset, content, viewport, expected) => {
    expect(clampScroll(offset, content, viewport)).toBe(expected);
  });

  it("returns a bounded window rather than clipping the underlying content", () => {
    expect(viewportLines(["a", "b", "c", "d", "e"], 99, 2)).toEqual(["d", "e"]);
  });

  it("reserves box chrome within the overlay height cap", () => {
    expect(overlayBodyRows(40)).toBe(22);
    expect(overlayBodyRows(10)).toBe(1);
  });
});
