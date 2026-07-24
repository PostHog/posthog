import { describe, expect, it } from "vitest";
import { formatCompactionFailure } from "./StatusNotificationView";

describe("formatCompactionFailure", () => {
  it.each([
    {
      error: "Compaction failed: Nothing to compact (session too small)",
      expected: "Compacting failed: Nothing to compact (session too small)",
    },
    {
      error: "Nothing to compact",
      expected: "Compacting failed: Nothing to compact",
    },
    { error: undefined, expected: "Compacting failed" },
  ])("formats $error without duplicate prefixes", ({ error, expected }) => {
    expect(formatCompactionFailure(error)).toBe(expected);
  });
});
