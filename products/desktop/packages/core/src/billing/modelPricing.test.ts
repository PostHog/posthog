import { describe, expect, it } from "vitest";
import {
  formatModelRates,
  modelCostInfo,
  modelListPrice,
  relativeCostLabel,
} from "./modelPricing";

describe("modelPricing", () => {
  it.each([
    ["claude-haiku-4-5-20251001", "0.5×"],
    ["claude-sonnet-5", "1×"],
    ["claude-opus-4-8", "2.5×"],
    ["claude-opus-5", "2.5×"],
    ["claude-fable-5", "5×"],
    ["gpt-5.6-sol", "2×"],
    ["gpt-5.6-terra", "≈1.1×"],
    ["gpt-5.6-luna", "≈0.11×"],
    ["gpt-5.5", "≈2.8×"],
    ["moonshotai/kimi-k3", "1.5×"],
    ["glm-5.3", "≈0.57×"],
    ["deepseek-v4", "≈0.05×"],
  ] as const)("%s -> %s", (modelId, expected) => {
    expect(modelCostInfo(modelId)?.multiplierLabel).toBe(expected);
  });

  it("returns null for unknown models so no wrong chip ever renders", () => {
    expect(modelCostInfo("totally-unknown-model")).toBeNull();
    expect(modelListPrice("totally-unknown-model")).toBeNull();
  });

  it("matches the specific gpt-5.6 tier before the gpt-5.5 family", () => {
    expect(modelListPrice("gpt-5.6-luna")?.inputPerMtok).toBe(0.2);
    expect(modelListPrice("gpt-5.5")?.inputPerMtok).toBe(5);
  });

  it("formats exact rates for tooltips", () => {
    const price = modelListPrice("gpt-5.6-luna");
    expect(price && formatModelRates(price)).toBe(
      "Input $0.20 · Output $1.20 per 1M tokens",
    );
  });

  it("compares two models for the switch dialog", () => {
    expect(relativeCostLabel("claude-opus-5", "claude-haiku-4-5")).toBe("0.2×");
    expect(relativeCostLabel("claude-haiku-4-5", "claude-fable-5")).toBe("10×");
    expect(relativeCostLabel("claude-opus-5", "claude-opus-4-8")).toBeNull();
    expect(relativeCostLabel("claude-opus-5", "unknown-model")).toBeNull();
  });
});
