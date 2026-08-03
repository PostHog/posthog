import { describe, expect, it } from "vitest";
import {
  getCapabilityLadder,
  getContextWindowOptions,
  getFastModeOptions,
  isSupportedReasoningEffort,
} from "./reasoning-effort";

describe("isSupportedReasoningEffort", () => {
  it("accepts xhigh for the codex gpt-5.5 family", () => {
    expect(isSupportedReasoningEffort("codex", "gpt-5.5", "xhigh")).toBe(true);
    expect(isSupportedReasoningEffort("codex", "gpt-5.5-codex", "xhigh")).toBe(
      true,
    );
  });

  it("rejects xhigh for other codex models", () => {
    expect(isSupportedReasoningEffort("codex", "gpt-5.3-codex", "xhigh")).toBe(
      false,
    );
  });

  it("accepts xhigh and max for the codex gpt-5.6 family", () => {
    expect(isSupportedReasoningEffort("codex", "gpt-5.6-luna", "xhigh")).toBe(
      true,
    );
    expect(isSupportedReasoningEffort("codex", "gpt-5.6-sol", "max")).toBe(
      true,
    );
  });

  it("rejects unknown effort values", () => {
    expect(isSupportedReasoningEffort("codex", "gpt-5.5", "ultra")).toBe(false);
    expect(isSupportedReasoningEffort("codex", "gpt-5.6-sol", "ultra")).toBe(
      false,
    );
  });

  it("gates xhigh on Claude models by id", () => {
    expect(
      isSupportedReasoningEffort("claude", "claude-opus-4-8", "xhigh"),
    ).toBe(true);
    expect(
      isSupportedReasoningEffort("claude", "claude-sonnet-4-6", "xhigh"),
    ).toBe(false);
  });

  it.each([
    ["high", true],
    ["max", true],
    ["low", false],
    ["medium", false],
    ["xhigh", false],
  ])("validates GLM 5.2 effort %s", (effort, expected) => {
    expect(
      isSupportedReasoningEffort("claude", "@cf/zai-org/glm-5.2", effort),
    ).toBe(expected);
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
  it.each([["claude"], ["codex"]] as const)(
    "returns five notches for %s",
    (adapter) => {
      expect(getCapabilityLadder(adapter)).toHaveLength(5);
    },
  );

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
