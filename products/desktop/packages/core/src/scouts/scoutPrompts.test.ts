import { describe, expect, it } from "vitest";
import { buildScoutFindingDiscussPrompt } from "./scoutPrompts";

const base = {
  skillName: "signals-scout-error-tracking",
  displayName: "Error tracking",
  runId: "run-abc",
  findingId: "finding-123",
  description: "Spike in TypeError on /checkout over the last hour.",
  severity: "high" as string | null,
  confidence: 0.82,
};

describe("buildScoutFindingDiscussPrompt", () => {
  it("includes the finding metadata, description, and scout skill", () => {
    const prompt = buildScoutFindingDiscussPrompt(base);

    expect(prompt).toContain("Error tracking scout");
    expect(prompt).toContain("`signals-scout-error-tracking`");
    expect(prompt).toContain("Run ID: run-abc");
    expect(prompt).toContain("Finding ID: finding-123");
    expect(prompt).toContain("Severity: high");
    expect(prompt).toContain("Confidence: 82%");
    expect(prompt).toContain(base.description);
    expect(prompt).toContain("exploring-signals-scouts");
  });

  it.each([
    {
      name: "leads with the user's question when one is provided",
      overrides: { question: "  Is this caused by the latest deploy?  " },
      contains: ["Answer this first: Is this caused by the latest deploy?"],
      notContains: ["brief readout"],
    },
    {
      name: "falls back to a readout for a whitespace-only question",
      overrides: { question: "   " },
      contains: ["brief readout"],
      notContains: ["Answer this first"],
    },
    {
      name: "falls back to a readout when no question is given",
      overrides: {},
      contains: ["brief readout"],
      notContains: ["Answer this first"],
    },
    {
      name: "omits the severity line when severity is null",
      overrides: { severity: null },
      contains: [],
      notContains: ["Severity:"],
    },
  ])("$name", ({ overrides, contains, notContains }) => {
    const prompt = buildScoutFindingDiscussPrompt({ ...base, ...overrides });

    for (const substring of contains) expect(prompt).toContain(substring);
    for (const substring of notContains)
      expect(prompt).not.toContain(substring);
  });
});
