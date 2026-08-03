import { describe, expect, it } from "vitest";
import { buildAppendedInstructions } from "./instructions";

describe("buildAppendedInstructions", () => {
  it("includes the spoken-narration block when narration is on", () => {
    const instructions = buildAppendedInstructions({ spokenNarration: true });
    expect(instructions).toContain("# Spoken Narration");
  });

  it("omits the spoken-narration block when narration is off", () => {
    const instructions = buildAppendedInstructions({ spokenNarration: false });
    expect(instructions).not.toContain("Spoken Narration");
  });

  it("keeps the base blocks in both modes", () => {
    const withNarration = buildAppendedInstructions({ spokenNarration: true });
    const withoutNarration = buildAppendedInstructions({
      spokenNarration: false,
    });
    expect(withNarration.startsWith(withoutNarration)).toBe(true);
    expect(withoutNarration.length).toBeGreaterThan(0);
  });
});
