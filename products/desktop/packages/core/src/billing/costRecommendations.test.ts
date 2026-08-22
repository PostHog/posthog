import { describe, expect, it } from "vitest";
import { modelNotchSuggestion } from "./costRecommendations";

describe("modelNotchSuggestion", () => {
  it.each([
    [
      "claude-opus-5",
      { fromModelId: "claude-opus-5", toModelId: "claude-sonnet-5" },
    ],
    [
      "claude-fable-5",
      { fromModelId: "claude-fable-5", toModelId: "claude-opus-5" },
    ],
    // Already at the cheapest priced rung on its ladder.
    ["claude-sonnet-5", null],
    // Below the trigger multiplier.
    ["claude-haiku-4-5", null],
    // No default set, and models with no known list price.
    [null, null],
    ["some-unpriced-model", null],
  ] as const)("%s", (modelId, expected) => {
    expect(modelNotchSuggestion(modelId)).toEqual(expected);
  });

  it("suggests a cheaper model on the codex ladder", () => {
    expect(modelNotchSuggestion("gpt-5.5")).toEqual({
      fromModelId: "gpt-5.5",
      toModelId: "gpt-5.6-sol",
    });
  });
});
