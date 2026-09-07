import { describe, expect, it } from "vitest";
import { hasVisibleDiffStats } from "./PrDiffIndicator";

describe("hasVisibleDiffStats", () => {
  it("hides all-zero diffs", () => {
    expect(hasVisibleDiffStats(0, 0)).toBe(false);
  });

  it("shows when either side is non-zero", () => {
    expect(hasVisibleDiffStats(12, 0)).toBe(true);
    expect(hasVisibleDiffStats(0, 3)).toBe(true);
    expect(hasVisibleDiffStats(12, 3)).toBe(true);
  });
});
