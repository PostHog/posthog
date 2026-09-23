import { describe, expect, it } from "vitest";
import {
  type CreateStep,
  type CreateStepContext,
  nextCreateStep,
  previousCreateStep,
} from "./createChannelSteps";

const base: CreateStepContext = {
  setupEnabled: true,
  choice: "none",
  visibility: "public",
};

describe("create channel steps", () => {
  it.each<[string, CreateStep, Partial<CreateStepContext>, CreateStep | null]>([
    [
      "flag off skips the setup step",
      "name",
      { setupEnabled: false },
      "describe",
    ],
    ["flag on asks what the space is for", "name", {}, "setup"],
    ["nothing goes to describe", "setup", {}, "describe"],
    ["a goal goes to the goal step", "setup", { choice: "goal" }, "goal"],
    [
      "a feature goes to the feature step",
      "setup",
      { choice: "feature" },
      "feature",
    ],
    [
      "goal details go to repositories",
      "goal",
      { choice: "goal" },
      "repositories",
    ],
    ["public ends at repositories", "repositories", {}, null],
    [
      "private continues to members",
      "repositories",
      { visibility: "private" },
      "members",
    ],
  ])("next: %s", (_name, step, context, expected) => {
    expect(nextCreateStep(step, { ...base, ...context })).toBe(expected);
  });

  it.each<[string, CreateStep, Partial<CreateStepContext>, CreateStep | null]>([
    ["describe returns to setup when the flag is on", "describe", {}, "setup"],
    [
      "describe returns to name when the flag is off",
      "describe",
      { setupEnabled: false },
      "name",
    ],
    [
      "repositories returns to the chosen detail step",
      "repositories",
      { choice: "feature" },
      "feature",
    ],
    [
      "repositories returns to describe for nothing",
      "repositories",
      {},
      "describe",
    ],
    ["name is the first step", "name", {}, null],
  ])("previous: %s", (_name, step, context, expected) => {
    expect(previousCreateStep(step, { ...base, ...context })).toBe(expected);
  });
});
