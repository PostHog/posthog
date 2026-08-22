import { describe, expect, it } from "vitest";
import { modelPriceTier, modelPriceTierMarker } from "./modelPriceTiers";

describe("modelPriceTier", () => {
  it.each([
    ["claude-haiku-4-5-20251001", 1],
    ["deepseek-v4", 1],
    ["glm-5.3", 1],
    ["claude-sonnet-5", 2],
    ["kimi-k3", 2],
    ["claude-opus-4-8", 3],
    ["claude-fable-5", 3],
    ["some-unknown-model", null],
  ] as const)("%s -> tier %s", (modelId, expected) => {
    expect(modelPriceTier(modelId)).toBe(expected);
  });

  it("renders ordinal dollar markers", () => {
    expect(modelPriceTierMarker(1)).toBe("$");
    expect(modelPriceTierMarker(3)).toBe("$$$");
  });
});
