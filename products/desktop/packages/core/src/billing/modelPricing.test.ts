import { customModelMeta } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  estimateUncachedInputCost,
  modelCostInfo,
  modelCostMultiplier,
  modelListPrice,
  toModelPickerOption,
} from "./modelPricing";

describe("modelPricing", () => {
  it.each([
    // The baseline anchors the scale; an exact ratio carries no ≈; diverging
    // input/output ratios earn one; sub-1 multipliers keep two decimals.
    ["claude-sonnet-5", "1×"],
    ["claude-opus-5", "2.5×"],
    ["gpt-5.5", "≈2.8×"],
    ["gpt-6-astra", "5×"],
    ["deepseek-ai/deepseek-v4-flash-0731", "≈0.05×"],
    ["zai-org/glm-5.3-flash", "≈0.06×"],
    // A picker hands back whichever form the gateway served.
    ["anthropic/claude-opus-5", "2.5×"],
    ["openai/gpt-6-sol", "1×"],
  ] as const)("%s -> %s", (modelId, expected) => {
    expect(modelCostInfo(modelId)?.multiplierLabel).toBe(expected);
  });

  it.each([
    // Absent from the catalog, then in it with no published price.
    "totally-unknown-model",
    "gpt-5",
  ] as const)("%s carries no price, so no wrong chip renders", (modelId) => {
    expect(modelCostInfo(modelId)).toBeNull();
    expect(modelListPrice(modelId)).toBeNull();
  });

  it("keeps an unpriced gateway model in the picker instead of throwing", () => {
    expect(
      toModelPickerOption({
        value: "future-gateway-model",
        name: "Future gateway model",
      }),
    ).toMatchObject({ kind: "unpriced", name: "Future gateway model" });

    expect(
      toModelPickerOption({
        value: "local-model",
        name: "Local model",
        _meta: customModelMeta(),
      }),
    ).toMatchObject({ kind: "custom" });
  });

  it("ranks models by the numeric multiplier the chips state", () => {
    const opus = modelCostMultiplier("claude-opus-5");
    const sonnet = modelCostMultiplier("claude-sonnet-5");
    expect(sonnet).toBe(1);
    expect(opus).toBe(2.5);
    expect(modelCostMultiplier("totally-unknown-model")).toBeNull();
  });

  it("carries the exact rates for tooltips", () => {
    // A sub-dollar rate exercises the two-decimal formatting the catalog does.
    expect(modelCostInfo("deepseek-ai/deepseek-v4-flash-0731")?.summary).toBe(
      "Input $0.13 · Output $0.26 per 1M tokens",
    );
  });

  it.each([
    ["gpt-5.6-terra", 100_000, 0.25],
    ["claude-sonnet-5", 50_000, 0.1],
    ["unknown-model", 100_000, null],
    ["claude-opus-5", 0, null],
  ] as const)(
    "estimates uncached input cost for %s with %s tokens",
    (modelId, tokens, expected) => {
      expect(estimateUncachedInputCost(modelId, tokens)).toBe(expected);
    },
  );
});
