import { describe, expect, it } from "vitest";
import { homeSubhead } from "./HomePage";

describe("homeSubhead", () => {
  it.each([
    [
      { suggestions: 3, experiments: 2, canvases: 1 },
      "3 feature flags to pick up, 2 experiments in flight, and 1 pinned canvas.",
    ],
    [
      { suggestions: 1, experiments: 0, canvases: 0 },
      "1 feature flag to pick up, below.",
    ],
    [
      { suggestions: 0, experiments: 2, canvases: 2 },
      "2 experiments in flight and 2 pinned canvases.",
    ],
  ])("counts what the page holds (%o)", (counts, expected) => {
    expect(homeSubhead(counts)).toBe(expected);
  });

  it("asks for a first space when there is nothing to show", () => {
    expect(homeSubhead({ suggestions: 0, experiments: 0, canvases: 0 })).toBe(
      "Start a space to give a piece of work its own place to happen.",
    );
  });
});
