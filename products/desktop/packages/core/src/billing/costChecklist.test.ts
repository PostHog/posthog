import { describe, expect, it } from "vitest";
import {
  buildCostChecklist,
  type CostChecklistInput,
  modelNotchSuggestion,
} from "./costChecklist";

const base: CostChecklistInput = {
  defaultModelId: "claude-sonnet-5",
  hasCustomImage: false,
  skills: [],
  completed: [],
};

describe("buildCostChecklist", () => {
  it("recommends an image when there is none, whatever else is set up", () => {
    expect(buildCostChecklist(base)).toEqual([
      { kind: "custom-image", done: false },
    ]);
  });

  it("checks the image row off the image itself, not a stored completion", () => {
    expect(buildCostChecklist({ ...base, hasCustomImage: true })).toEqual([
      { kind: "custom-image", done: true },
    ]);
    // A build that was started and then failed or deleted leaves the stored
    // kind behind; the row must go back to unchecked all the same.
    expect(
      buildCostChecklist({ ...base, completed: ["custom-image"] }),
    ).toEqual([{ kind: "custom-image", done: false }]);
  });

  it("omits the image row when the account is not known or custom images are off", () => {
    // Null means unavailable or not yet loaded, so no image row appears at all
    // rather than a suggestion the user cannot act on.
    expect(buildCostChecklist({ ...base, hasCustomImage: null })).toEqual([]);
    expect(
      buildCostChecklist({
        ...base,
        hasCustomImage: null,
        completed: ["custom-image"],
      }),
    ).toEqual([]);
  });

  it("keeps a completed item as a checked record and sinks it below active work", () => {
    const items = buildCostChecklist({
      ...base,
      defaultModelId: "claude-sonnet-5",
      completed: ["model-notch"],
    });
    expect(items).toEqual([
      { kind: "custom-image", done: false },
      { kind: "model-notch", done: true, modelId: "claude-sonnet-5" },
    ]);
  });

  it("re-fires the suggestion when the default still warrants one after completion", () => {
    const items = buildCostChecklist({
      ...base,
      defaultModelId: "claude-opus-5",
      hasCustomImage: true,
      completed: ["model-notch"],
    });
    // A stored completion does not hold the row checked once the current
    // default is expensive again; the cheaper-model suggestion comes back.
    expect(items).toEqual([
      {
        kind: "model-notch",
        done: false,
        fromModelId: "claude-opus-5",
        toModelId: "claude-sonnet-5",
      },
      { kind: "custom-image", done: true },
    ]);
  });

  it("gives every skill its own row, installed ones below the rest", () => {
    expect(
      buildCostChecklist({
        ...base,
        hasCustomImage: true,
        skills: [
          { skillId: "ponytail", name: "Ponytail", installed: true },
          {
            skillId: "context-budget",
            name: "Context budget",
            installed: false,
          },
        ],
      }),
    ).toEqual([
      {
        kind: "install-skill",
        done: false,
        skillId: "context-budget",
        name: "Context budget",
      },
      { kind: "custom-image", done: true },
      {
        kind: "install-skill",
        done: true,
        skillId: "ponytail",
        name: "Ponytail",
      },
    ]);
  });
});

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
    // Sol matches gpt-5.5 per token, so the notch down is the cheaper Terra.
    expect(modelNotchSuggestion("gpt-5.5")).toEqual({
      fromModelId: "gpt-5.5",
      toModelId: "gpt-5.6-terra",
    });
  });
});
