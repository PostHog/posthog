import { describe, expect, it } from "vitest";
import { isAnthropicModelId } from "./cloud-task-models";
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

describe("isAnthropicModelId", () => {
  it.each([
    ["claude-sonnet-5", true],
    ["anthropic/claude-opus-4", true],
    ["@cf/zai-org/glm-5.2", false],
    ["modal/claude-3", false],
    ["deepseek/deepseek-chat", false],
    ["glm-4", false],
    ["baseten/claude-3", false],
    ["gpt-5", false],
    ["", false],
  ] as const)("%s -> %s", (modelId, expected) => {
    expect(isAnthropicModelId(modelId)).toBe(expected);
  });
});
