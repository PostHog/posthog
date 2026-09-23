import type { SpaceSetupChoice } from "@posthog/core/canvas/spaceSetup";

export const CREATE_STEPS = [
  "name",
  "setup",
  "describe",
  "goal",
  "feature",
  "repositories",
  "members",
] as const;
export type CreateStep = (typeof CREATE_STEPS)[number];

export interface CreateStepContext {
  /** The "set up this space for" step is flag-gated; off, the flow is name → describe. */
  setupEnabled: boolean;
  choice: SpaceSetupChoice;
  visibility: "public" | "private";
}

/** The step that follows `step` for this draft, or null on the last step. */
export function nextCreateStep(
  step: CreateStep,
  context: CreateStepContext,
): CreateStep | null {
  switch (step) {
    case "name":
      return context.setupEnabled ? "setup" : "describe";
    case "setup":
      return context.choice === "none" ? "describe" : context.choice;
    case "describe":
    case "goal":
    case "feature":
      return "repositories";
    case "repositories":
      return context.visibility === "private" ? "members" : null;
    case "members":
      return null;
  }
}

/** The step before `step` for this draft, or null on the first step. */
export function previousCreateStep(
  step: CreateStep,
  context: CreateStepContext,
): CreateStep | null {
  switch (step) {
    case "name":
      return null;
    case "setup":
      return "name";
    case "describe":
      return context.setupEnabled ? "setup" : "name";
    case "goal":
    case "feature":
      return "setup";
    case "repositories":
      return context.choice === "none" ? "describe" : context.choice;
    case "members":
      return "repositories";
  }
}

export function createStepDirection(from: CreateStep, to: CreateStep): 1 | -1 {
  return CREATE_STEPS.indexOf(to) > CREATE_STEPS.indexOf(from) ? 1 : -1;
}
