import type { SpaceSetupChoice } from "@posthog/core/canvas/spaceSetup";

export const CREATE_STEPS = [
  "name",
  "setup",
  "describe",
  "repositories",
  "members",
] as const;
export type CreateStep = (typeof CREATE_STEPS)[number];

export interface CreateStepContext {
  /** The "what is this space for" step is flag-gated; off, the flow keeps the describe step. */
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
    case "describe":
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
    case "describe":
      return "name";
    case "repositories":
      return context.setupEnabled ? "setup" : "describe";
    case "members":
      return "repositories";
  }
}

export function createStepDirection(from: CreateStep, to: CreateStep): 1 | -1 {
  return CREATE_STEPS.indexOf(to) > CREATE_STEPS.indexOf(from) ? 1 : -1;
}
