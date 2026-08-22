import { describe, expect, it } from "vitest";
import { buildCostChecklist, type CostChecklistInput } from "./costChecklist";

const base: CostChecklistInput = {
  defaultModelId: "claude-sonnet-5",
  cloudRepository: null,
  cloudRepositoryHasCustomImage: false,
  hasSpendHistory: false,
  skills: [],
  completed: [],
};

describe("buildCostChecklist", () => {
  it("is empty when no trigger fires", () => {
    expect(buildCostChecklist(base)).toEqual([]);
  });

  it("offers the model notch only above the trigger multiplier", () => {
    expect(
      buildCostChecklist({ ...base, defaultModelId: "claude-opus-5" }),
    ).toEqual([
      {
        kind: "model-notch",
        done: false,
        fromModelId: "claude-opus-5",
        toModelId: "claude-sonnet-5",
      },
    ]);
  });

  it("offers a custom image only for a cloud repo that lacks one", () => {
    expect(
      buildCostChecklist({ ...base, cloudRepository: "posthog/posthog" }),
    ).toEqual([
      { kind: "custom-image", done: false, repository: "posthog/posthog" },
    ]);
    expect(
      buildCostChecklist({
        ...base,
        cloudRepository: "posthog/posthog",
        cloudRepositoryHasCustomImage: true,
      }),
    ).toEqual([]);
  });

  it("keeps a completed item as a checked record and sinks it below active work", () => {
    const items = buildCostChecklist({
      ...base,
      defaultModelId: "claude-sonnet-5",
      cloudRepository: "posthog/posthog",
      completed: ["model-notch"],
    });
    expect(items).toEqual([
      { kind: "custom-image", done: false, repository: "posthog/posthog" },
      { kind: "model-notch", done: true, modelId: "claude-sonnet-5" },
    ]);
  });

  it("never shows an item twice when its trigger still fires after completion", () => {
    const items = buildCostChecklist({
      ...base,
      defaultModelId: "claude-opus-5",
      completed: ["model-notch"],
    });
    expect(items).toEqual([
      { kind: "model-notch", done: true, modelId: "claude-opus-5" },
    ]);
  });

  it("offers a skill only once there is spend to reduce", () => {
    const skills = [
      { skillId: "ponytail", name: "Ponytail", installed: false },
    ];
    expect(buildCostChecklist({ ...base, skills })).toEqual([]);
    expect(
      buildCostChecklist({ ...base, skills, hasSpendHistory: true }),
    ).toEqual([
      {
        kind: "install-skill",
        done: false,
        skillId: "ponytail",
        name: "Ponytail",
      },
    ]);
  });

  it("gives every skill its own row, installed ones below the rest", () => {
    expect(
      buildCostChecklist({
        ...base,
        hasSpendHistory: true,
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
      {
        kind: "install-skill",
        done: true,
        skillId: "ponytail",
        name: "Ponytail",
      },
    ]);
  });

  it("keeps an installed skill's row whatever the spend history", () => {
    expect(
      buildCostChecklist({
        ...base,
        skills: [{ skillId: "ponytail", name: "Ponytail", installed: true }],
      }),
    ).toEqual([
      {
        kind: "install-skill",
        done: true,
        skillId: "ponytail",
        name: "Ponytail",
      },
    ]);
  });
});
