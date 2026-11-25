import { describe, expect, it } from "vitest";
import {
  getCapabilityLadder,
  getContextWindowOptions,
  getFastModeOptions,
  isSupportedReasoningEffort,
} from "./reasoning-effort";

describe("isSupportedReasoningEffort", () => {
  it.each([
    ["codex", "gpt-5.5", "xhigh", true],
    ["codex", "gpt-5.5", "max", false],
    ["codex", "gpt-5.5", "ultra", false],
    ["codex", "gpt-5.3-codex", "xhigh", true],
    ["codex", "gpt-5.6-luna", "xhigh", true],
    ["codex", "gpt-5.6-sol", "max", true],
    ["claude", "claude-opus-4-8", "xhigh", true],
    ["claude", "claude-sonnet-4-6", "xhigh", false],
    ["claude", "claude-sonnet-4-6", "max", true],
    ["claude", "deepseek-ai/deepseek-v4-flash-0731", "high", true],
    ["claude", "gpt-5.5", "high", false],
    ["codex", "gpt-6.3-sol", "max", true],
    ["codex", "openai/gpt-6.3-sol", "max", true],
    ["codex", "gpt-6.3-sol", "ultracode", false],
    ["codex", "gpt-6.3-sol", "ultra", false],
    ["codex", "gpt-5.5-codex", "xhigh", true],
    ["claude", "claude-opus-9", "ultracode", true],
    ["claude", "@cf/zai-org/glm-5.2", "high", true],
    ["claude", "@cf/zai-org/glm-5.2", "low", true],
    ["claude", "@cf/zai-org/glm-5.2", "ultracode", false],
  ] as const)("takes %s %s at %s: %s", (adapter, modelId, effort, expected) => {
    expect(isSupportedReasoningEffort(adapter, modelId, effort)).toBe(expected);
  });

  it.each([
    ["claude-opus-4-8", "ultracode", true],
    ["claude-sonnet-4-6", "ultracode", false],
    ["@cf/zai-org/glm-5.2", "ultracode", false],
  ])("gates ultracode on Claude model %s (%s)", (modelId, effort, expected) => {
    expect(isSupportedReasoningEffort("claude", modelId, effort)).toBe(
      expected,
    );
  });

  it("never offers ultracode on codex models", () => {
    expect(
      isSupportedReasoningEffort("codex", "gpt-5.6-sol", "ultracode"),
    ).toBe(false);
  });
});

const ladderCases = (["claude", "codex"] as const).flatMap((adapter) =>
  getCapabilityLadder(adapter).map(
    (notch) => [adapter, notch.model, notch.effort] as const,
  ),
);

describe("getCapabilityLadder", () => {
  it.each([
    ["claude", 5],
    ["codex", 6],
  ] as const)(
    "returns the expected notches for %s",
    (adapter, expectedLength) => {
      expect(getCapabilityLadder(adapter)).toHaveLength(expectedLength);
    },
  );

  it("uses GPT-6 Astra at Max as the smartest Codex notch", () => {
    expect(getCapabilityLadder("codex").at(-1)).toEqual({
      model: "gpt-6-astra",
      effort: "max",
    });
  });

  it.each(ladderCases)(
    "pairs a supported effort at every notch (%s %s %s)",
    (adapter, model, effort) => {
      expect(isSupportedReasoningEffort(adapter, model, effort)).toBe(true);
    },
  );
});

describe("getContextWindowOptions", () => {
  it("returns null for codex", () => {
    expect(getContextWindowOptions("codex", "gpt-5.6-sol")).toBeNull();
  });

  it("returns 200k and 1m for a 1M-capable Claude model", () => {
    expect(
      getContextWindowOptions("claude", "claude-opus-5")?.map((o) => o.value),
    ).toEqual(["200k", "1m"]);
  });
});

describe("getFastModeOptions", () => {
  it("returns null for codex", () => {
    expect(getFastModeOptions("codex", "gpt-5.6-sol")).toBeNull();
  });

  it.each([
    ["claude-opus-5", true],
    ["claude-sonnet-5", false],
  ])("gates Claude fast mode by model (%s)", (modelId, supported) => {
    const values = getFastModeOptions("claude", modelId)?.map((o) => o.value);
    expect(values ?? null).toEqual(supported ? ["on", "off"] : null);
  });
});
