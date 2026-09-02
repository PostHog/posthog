import { describe, expect, it } from "vitest";
import {
  buildBreakdown,
  emptyBaseline,
  estimateJsonTokens,
  estimateMcpTokens,
  estimateRulesTokens,
  estimateSkillsTokens,
  estimateSystemPrompt,
  estimateTokens,
} from "./context-breakdown";

describe("estimateTokens", () => {
  it("returns 0 for empty input", () => {
    expect(estimateTokens("")).toBe(0);
    expect(estimateTokens(undefined)).toBe(0);
    expect(estimateTokens(null)).toBe(0);
  });

  it("scales roughly with input length", () => {
    expect(estimateTokens("a".repeat(40))).toBe(10);
    expect(estimateTokens("a".repeat(400))).toBe(100);
  });
});

describe("estimateJsonTokens", () => {
  it("counts JSON representation of objects", () => {
    const tokens = estimateJsonTokens({ name: "Read", schema: { foo: 1 } });
    expect(tokens).toBeGreaterThan(0);
  });

  it("returns 0 for non-serializable values", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(estimateJsonTokens(circular)).toBe(0);
  });
});

describe("estimateSystemPrompt", () => {
  it("includes the Claude preset budget when preset is used", () => {
    const noAppend = estimateSystemPrompt({ type: "preset" });
    expect(noAppend).toBeGreaterThan(0);
  });

  it("adds the append portion on top of the preset", () => {
    const append = "a".repeat(400);
    const result = estimateSystemPrompt({ type: "preset", append });
    const presetOnly = estimateSystemPrompt({ type: "preset" });
    expect(result - presetOnly).toBe(100);
  });

  it("counts a raw string verbatim with no preset overhead", () => {
    expect(estimateSystemPrompt("a".repeat(400))).toBe(100);
  });

  it("treats undefined as the bare preset", () => {
    expect(estimateSystemPrompt(undefined)).toBe(
      estimateSystemPrompt({ type: "preset" }),
    );
  });
});

describe("estimateSkillsTokens", () => {
  it("is 0 for an empty command list", () => {
    expect(estimateSkillsTokens([])).toBe(0);
  });

  it("counts the JSON of name/description/hint", () => {
    // [{"name":"review","description":"Review a PR","hint":"[pr]"}] ~ 55 chars
    const result = estimateSkillsTokens([
      { name: "review", description: "Review a PR", input: { hint: "[pr]" } },
    ]);
    expect(result).toBeGreaterThan(10);
    expect(result).toBeLessThan(20);
  });
});

describe("estimateMcpTokens", () => {
  it("is 0 for no connected tools", () => {
    expect(estimateMcpTokens([])).toBe(0);
  });

  it("scales with tool count", () => {
    const one = estimateMcpTokens([{ name: "get_user", description: "x" }]);
    const many = estimateMcpTokens(
      Array.from({ length: 50 }, (_, i) => ({
        name: `tool_${i}`,
        description: "x",
      })),
    );
    expect(many).toBeGreaterThan(one * 10);
  });
});

describe("estimateRulesTokens", () => {
  it("is 0 for missing rules", () => {
    expect(estimateRulesTokens(undefined)).toBe(0);
    expect(estimateRulesTokens("")).toBe(0);
  });

  it("counts the rules content", () => {
    expect(estimateRulesTokens("a".repeat(400))).toBe(100);
  });
});

describe("buildBreakdown", () => {
  it("derives conversation from input - stable sum", () => {
    const baseline = {
      ...emptyBaseline(),
      systemPrompt: 4000,
      tools: 500,
    };
    const result = buildBreakdown(baseline, 10_000);
    expect(result.systemPrompt).toBe(4000);
    expect(result.tools).toBe(500);
    expect(result.conversation).toBe(5500);
  });

  it("floors conversation at 0 when stable pieces exceed input", () => {
    const baseline = { ...emptyBaseline(), systemPrompt: 5000 };
    expect(buildBreakdown(baseline, 1000).conversation).toBe(0);
  });

  it("includes zero categories", () => {
    const result = buildBreakdown(emptyBaseline(), 100);
    expect(result.mcp).toBe(0);
    expect(result.skills).toBe(0);
    expect(result.subagents).toBe(0);
  });
});
