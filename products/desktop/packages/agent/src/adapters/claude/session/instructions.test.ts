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

  it.each([
    "# Branch Naming",
    "# Pull Request Links",
    "# Plan Mode",
    "# MCP Tool Access",
    "# Data Handling",
    "# Shell Efficiency",
  ])("always appends %s", (heading) => {
    expect(buildAppendedInstructions({ spokenNarration: false })).toContain(
      heading,
    );
  });

  it("includes the context wiki block only when a mount path is given", () => {
    const mounted = buildAppendedInstructions({
      spokenNarration: false,
      contextWikiPath: "/tmp/workspace/context",
    });
    expect(mounted).toContain("# Context Wiki");
    expect(mounted).toContain("mounted at /tmp/workspace/context");
    expect(
      buildAppendedInstructions({ spokenNarration: false }),
    ).not.toContain("Context Wiki");
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
