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
      "flag off keeps the describe step",
      "name",
      { setupEnabled: false },
      "describe",
    ],
    ["flag on asks what the space is for", "name", {}, "setup"],
    [
      "the setup step goes to repositories",
      "setup",
      { choice: "goal" },
      "repositories",
    ],
    [
      "describe goes to repositories",
      "describe",
      { setupEnabled: false },
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
    [
      "repositories returns to setup when the flag is on",
      "repositories",
      {},
      "setup",
    ],
    [
      "repositories returns to describe when the flag is off",
      "repositories",
      { setupEnabled: false },
      "describe",
    ],
    ["setup returns to name", "setup", {}, "name"],
    ["name is the first step", "name", {}, null],
  ])("previous: %s", (_name, step, context, expected) => {
    expect(previousCreateStep(step, { ...base, ...context })).toBe(expected);
  });
});
