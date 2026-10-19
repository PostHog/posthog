import { describe, expect, it } from "vitest";
import { formatCompactBoundaryLabel } from "./CompactBoundaryView";

describe("formatCompactBoundaryLabel", () => {
  it.each([
    {
      name: "missing metadata",
      props: {},
      expected: "Conversation compacted",
    },
    {
      name: "token count without context size",
      props: { trigger: "auto" as const, preTokens: 12_400 },
      expected: "Conversation compacted · auto · ~12K tokens",
    },
    {
      name: "percentage with context size",
      props: {
        trigger: "manual" as const,
        preTokens: 75_000,
        contextSize: 100_000,
      },
      expected: "Conversation compacted · manual · 75% of context",
    },
  ])("formats $name", ({ props, expected }) => {
    expect(formatCompactBoundaryLabel(props)).toBe(expected);
  });
});
