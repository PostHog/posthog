import { describe, expect, it } from "vitest";
import { isTriageSummaryHotkey } from "./ReportTriageFocus";

describe("isTriageSummaryHotkey", () => {
  it.each([
    ["lowercase S", "s", false, false, false, true],
    ["uppercase S", "S", false, false, false, true],
    ["Enter", "Enter", false, false, false, false],
    ["Command+S", "s", true, false, false, false],
    ["Control+S", "s", false, true, false, false],
    ["Alt+S", "s", false, false, true, false],
  ] as const)(
    "%s is handled=%s",
    (_label, key, metaKey, ctrlKey, altKey, expected) => {
      expect(isTriageSummaryHotkey({ key, metaKey, ctrlKey, altKey })).toBe(
        expected,
      );
    },
  );
});
