import { describe, expect, it } from "vitest";
import { formatDockBadge } from "./dockBadge";

describe("formatDockBadge", () => {
  it.each([
    ["clears at zero", 0, ""],
    ["clears below zero", -3, ""],
    ["clears when not finite", Number.NaN, ""],
    ["shows a single item", 1, "1"],
    ["shows the cap exactly", 99, "99"],
    ["caps above the limit", 100, "99+"],
    ["truncates a fraction", 2.7, "2"],
  ])("%s", (_label, count, expected) => {
    expect(formatDockBadge(count)).toBe(expected);
  });
});
