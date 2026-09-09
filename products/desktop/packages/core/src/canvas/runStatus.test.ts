import { describe, expect, it } from "vitest";
import { runStatusLabel, runStatusVariant } from "./runStatus";

describe("runStatusLabel", () => {
  it.each([
    ["completed", "Ready"],
    ["in_progress", "In progress"],
    ["not_started", "Not started"],
    ["queued", "Queued"],
    ["failed", "Failed"],
    ["cancelled", "Cancelled"],
  ] as const)("labels %s as %s", (status, expected) => {
    expect(runStatusLabel(status)).toBe(expected);
  });

  it.each([null, undefined])("returns null for %s", (status) => {
    expect(runStatusLabel(status)).toBeNull();
  });
});

describe("runStatusVariant", () => {
  it.each([
    ["completed", "success"],
    ["failed", "destructive"],
    ["in_progress", "info"],
    ["queued", "default"],
    ["not_started", "default"],
    ["cancelled", "default"],
  ] as const)("maps %s to %s", (status, expected) => {
    expect(runStatusVariant(status)).toBe(expected);
  });

  it("falls back to default when there is no run", () => {
    expect(runStatusVariant(null)).toBe("default");
  });
});
