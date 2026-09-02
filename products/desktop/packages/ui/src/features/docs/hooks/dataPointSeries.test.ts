import { describe, expect, it } from "vitest";
import { seriesKind } from "./dataPointSeries";

describe("dataPointSeries", () => {
  it.each([
    [
      "days",
      [
        ["2026-08-30", 12],
        ["2026-08-31", 20],
      ],
      "time",
    ],
    [
      "timestamps",
      [
        ["2026-08-30 00:00:00", 12],
        ["2026-08-31T00:00:00Z", 20],
      ],
      "time",
    ],
    [
      "events",
      [
        ["$pageview", 12],
        ["$autocapture", 20],
      ],
      "categories",
    ],
    ["bare numbers", [[12], [20]], "time"],
  ])("reads a series of %s as %s", (_name, rows, expected) => {
    expect(seriesKind(rows)).toBe(expected);
  });
});
