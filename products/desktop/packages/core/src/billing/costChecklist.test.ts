import { describe, expect, it } from "vitest";
import { buildCostChecklist, type CostChecklistInput } from "./costChecklist";

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

  it("offers the model notch only above the trigger multiplier", () => {
    expect(
      buildCostChecklist({
        ...base,
        defaultModelId: "claude-opus-5",
        hasCustomImage: true,
      }),
    ).toEqual([
      {
        kind: "model-notch",
        done: false,
        fromModelId: "claude-opus-5",
        toModelId: "claude-sonnet-5",
      },
      { kind: "custom-image", done: true },
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

  it("never shows an item twice when its trigger still fires after completion", () => {
    const items = buildCostChecklist({
      ...base,
      defaultModelId: "claude-opus-5",
      hasCustomImage: true,
      completed: ["model-notch"],
    });
    expect(items).toEqual([
      { kind: "model-notch", done: true, modelId: "claude-opus-5" },
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
