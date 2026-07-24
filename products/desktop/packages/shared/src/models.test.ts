import { describe, expect, it } from "vitest";
import { defaultEligibleModel } from "./models";

describe("defaultEligibleModel", () => {
  it.each([
    ["claude-fable-5", undefined],
    ["anthropic/claude-fable-5", undefined],
    ["CLAUDE-FABLE-5", undefined],
    ["claude-fable-5-20260601", undefined],
    ["claude-opus-4-8", "claude-opus-4-8"],
    ["claude-sonnet-5", "claude-sonnet-5"],
    ["gpt-5.5", "gpt-5.5"],
    ["@cf/zai-org/glm-5.2", "@cf/zai-org/glm-5.2"],
    // Contains "fable" as a substring but is not the Fable family.
    ["gpt-affable-1", "gpt-affable-1"],
    ["", undefined],
    [null, undefined],
    [undefined, undefined],
  ] as const)("%s -> %s", (modelId, expected) => {
    expect(defaultEligibleModel(modelId)).toBe(expected);
  });
});
