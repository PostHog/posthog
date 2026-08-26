import { describe, expect, it } from "vitest";
import { migrateOnboardingState } from "./onboardingStore";

describe("migrateOnboardingState", () => {
  it.each(["welcome", "import-config", "invite-code"])(
    "resets the retired %s step to the first step",
    (retiredStep) => {
      const migrated = migrateOnboardingState({
        currentStep: retiredStep,
        hasCompletedOnboarding: false,
        hasShippedFirstPr: false,
        selectedProjectId: 1,
      });

      expect(migrated.currentStep).toBe("project-select");
    },
  );

  it("keeps a current step unchanged", () => {
    const migrated = migrateOnboardingState({
      currentStep: "consent",
      hasCompletedOnboarding: false,
      hasShippedFirstPr: false,
      selectedProjectId: 1,
    });

    expect(migrated.currentStep).toBe("consent");
  });
});
