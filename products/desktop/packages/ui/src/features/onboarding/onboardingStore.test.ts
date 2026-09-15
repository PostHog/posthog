import { describe, expect, it } from "vitest";
import { migrateOnboardingState } from "./onboardingStore";

describe("migrateOnboardingState", () => {
  const persisted = (currentStep: string) => ({
    currentStep,
    hasCompletedOnboarding: false,
    hasShippedFirstPr: false,
    selectedProjectId: 1,
  });

  it("moves a persisted invite-code step forward", () => {
    expect(migrateOnboardingState(persisted("invite-code")).currentStep).toBe(
      "consent",
    );
  });

  it.each(["welcome", "import-config"])(
    "resets the retired %s step to the start of the flow",
    (step) => {
      expect(migrateOnboardingState(persisted(step)).currentStep).toBe(
        "project-select",
      );
    },
  );

  it("leaves a step of the current flow alone", () => {
    expect(migrateOnboardingState(persisted("select-repo")).currentStep).toBe(
      "select-repo",
    );
  });
});
